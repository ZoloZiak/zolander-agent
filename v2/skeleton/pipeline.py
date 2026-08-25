"""pipeline — orchestrácia inbound toku (poradie vrstiev je závazné).

ADRESUJE (REPORT.md VERDIKT): zlyhania sú „lokalizované v štyroch vrstvách
(output-channel filter, trust-ordering, stavový automat, persona hook)".
Pipeline ich skladá do jediného toku s pevným poradím, kde trust-ordering
je vynútený štruktúrou, nie disciplínou.

TOK (inbound):
  1. routing.SpaceRouter.classify      -> SpaceKind (infra rozhodnutie)
  2. KRYPTO VERIFIKÁCIA PRED vetvením is_a2a (VALIDÁCIA #1) — každá správa
     nosiaca pubkey+signature sa overí VŽDY cez A2AGate.verify_signature;
     neplatný podpis = drop ešte pred akýmkoľvek vetvením.
  3. a2a_gate.A2AGate.check            -> dedup event_id / known peers (A2A)
  4. trust_boundary.TrustBoundary      -> KNOWN_PEER vs karanténa (pred auto-reply!)
  5. state_machine.begin               -> idempotencia (raz a len raz)
  6. media_pipeline                    -> dekóduj prílohy (shell-safe)
  7. detekcia korekcií -> state_machine.apply_correction (VALIDÁCIA #2)
  8. persona_hook.build_instruction    -> jazyk-mirror + anti-korpobot
  9. LLM call (injektovaný callable — mimo tejto vrstvy)
 10. persona_hook.style_check          -> mechanický štýl výstupu (VALIDÁCIA #8)
 11. output_filter.filter              -> typová whitelist obálky von (#4)
 12. routing.guard_outbound + send-once -> A2A nikdy do GROUP/UNKNOWN
     (KONS #9, VALIDÁCIA #4 revalidate), potom jediné odoslanie

VALIDÁCIA #3: sanitize_content sa volá aj na akceptovanej KNOWN_PEER ceste
(telo správy ide modelu ako citovaný obsah, nie ako direktíva — injection
z trusted peera je reálny vektor).

Fail-safe (BRIEF pravidlo 3): žiadna výnimka z jednotlivých vrstiev nezabije
pipeline — loguje sa a event sa degraduje (complete('failed')).
"""
from __future__ import annotations

import re
import sys
from typing import Callable, List, Optional, Tuple

from .types import Channel, Envelope, OutgoingMessage, SpaceKind, TrustState

# LLM callable: (system_prompt, user_text) -> odpoveď modelu
LLMFn = Callable[[str, str], Optional[str]]

# VALIDÁCIA #2: pravidlá detekcie výčitky/korekcie z textu správy.
# Prvý záznam je reálny dôkaz z incidentu [46813:L4210]:
#   „po nevhodne mi wyswietlasz co robisz"
CORRECTION_RULES: Tuple[Tuple[re.Pattern, str, object], ...] = (
    # progress/thinking/status nemajú ísť ku kontaktu
    # (dôkaz [46813:L4210]: „po nevhodne mi wyswietlasz co robisz")
    (re.compile(r"(?i)\bwyswietlasz\b|\bwyswietla[sś]\b"), "suppress_progress", True),
    (re.compile(r"(?i)nezobrazuj\b|\bneposielaj\b|\bpresta[nň]\s+(mi\s+)?(posiel|zobraz|písat)"),
     "suppress_progress", True),
    (re.compile(r"(?i)stop\s+(showing\s+)?(me\s+)?(the\s+)?(progress|thinking|status|internals)"),
     "suppress_progress", True),
    (re.compile(r"(?i)(žiadny|ziadny|no)\s+(intern[yý]\s+)?(progress|progres|status)\b"),
     "suppress_progress", True),
)


class InboundPipeline:
    """Zostavuje a vykonáva poradie vrstiev pre jeden prichádzajúci event."""

    def __init__(self,
                 router=None,
                 a2a_gate=None,
                 trust=None,
                 state=None,
                 media=None,
                 persona=None,
                 output=None,
                 cmd_guard=None,
                 llm_fn: Optional[LLMFn] = None,
                 state_persist_path: Optional[str] = None,
                 allow_plain_chat: bool = False,
                 persona_profile=None,
                 corrector=None) -> None:
        """Komponenty sú injektovateľné (DI); bez nich sa postavia defaulty.

        VALIDÁCIA #5: `allow_plain_chat` má default **False**. Dopad:
        obyčajný chat BEZ krypto identity (žiadny pubkey/signature, napr.
        Paulinin plain WhatsApp/Matrix DM) NEODPOVEDÁ automaticky — ide do
        QUARANTINE ako whitelisted-unverified (auto-reply zamknutá, rate-limit,
        obsah len ako citovaný náhľad pre operátora). Jediná cesta von je
        manuálne schválenie operátorom (`trust add <fp>`). Kto chce v1-like
        správanie, musí to explicitne zapnúť (allow_plain_chat=True) — tým
        priznáva, že KONS. #3 nie je krytá.

        A2A / identity-claiming správy musia byť VŽDY krypto-overené pred
        akoukoľvek odpoveďou (KONS. #3), bez ohľadu na tento flag.
        """
        from .a2a_gate import A2AGate
        from .cmd_guard_v2 import CmdGuardV2
        from .correction_learner import CorrectionLearner
        from .media_pipeline import MediaPipeline
        from .output_filter import OutputFilter
        from .persona_hook import PersonaHook
        from .persona_profile import PersonaProfile
        from .routing import SpaceRouter
        from .state_machine import EventStateMachine
        from .trust_boundary import TrustBoundary

        self.router = router or SpaceRouter()
        self.a2a_gate = a2a_gate or A2AGate()
        self.trust = trust or TrustBoundary()
        self.state = state or EventStateMachine(persist_path=state_persist_path)
        self.media = media or MediaPipeline()
        self.persona = persona or PersonaHook()
        self.output = output or OutputFilter()
        self.cmd_guard = cmd_guard or CmdGuardV2(audit_path="cmd_audit.jsonl")
        # FÁZA 6: persona profil (global + per-peer) a correction learner.
        # data_dir=None => in-memory; caller môže podať vlastný s perzistenciou.
        self.persona_profile = persona_profile or PersonaProfile(data_dir=None)
        self.corrector = corrector or CorrectionLearner(self.persona_profile)
        self.llm_fn = llm_fn   # LLM zostáva mimo skeletonu (injekcia)
        self.allow_plain_chat = allow_plain_chat
        # VALIDÁCIA #1: krypto-verifikátor je napojený VŽDY — trust vrstva
        # overuje podpis každej správy nosiacej pubkey+signature, nie len A2A.
        try:
            self.trust.set_verify_fn(self.a2a_gate.verify_signature)
        except Exception:  # noqa: BLE001 — custom trust bez set_verify_fn
            pass

    def handle(self, env: Envelope, member_count: Optional[int] = None) -> Optional[str]:
        """Spracuj prichádzajúci event podľa TOK vyššie.

        Vracia finálny text odoslaný do externého kanalu, alebo None ak bol
        event dropnutý/karanténovaný/duplicitný. Nikdy nevyhodí výnimku von.
        """
        try:
            # 1. routing: klasifikácia priestoru je infra rozhodnutie (KONS. #9)
            kind = self.router.classify(env, member_count=member_count)
            env.kind = kind

            # 2. VALIDÁCIA #1: Ed25519 verify PRED vetvením is_a2a.
            #    Každá správa nosiaca pubkey+signature sa overí VŽDY — útok
            #    „ukradni pubkey peera a pošli plain message" padne tu, lebo
            #    hash-väzba sha256(pubkey)==fp je triviálne splniteľná.
            signature_ok: Optional[bool] = None
            carries_identity = bool(env.pubkey and env.signature)
            if carries_identity:
                signature_ok = bool(self.a2a_gate.verify_signature(env))
                if not signature_ok:
                    self._log(f"signature verify FAILED before branching "
                              f"on {env.event_id} — dropped")
                    self._finish(env.event_id, "dropped")
                    return None

            # 3. a2a_gate: dedup + known peers pre A2A obálky (KONS. #5)
            if env.is_a2a:
                verdict = self.a2a_gate.check(env)
                if not verdict.allow and verdict.drop_fast:
                    self._finish(env.event_id, "dropped")
                    return None
                signature_ok = verdict.allow

            # 4. trust_boundary PRED akoukoľvek auto-reply (KONS. #3).
            #    Krypto hranica platí tvrdo pre A2A / identity-claiming správy;
            #    obyčajný chat (bez pubkey) púšťame len ak allow_plain_chat
            #    (default False — VALIDÁCIA #5).
            identity_claimed = env.is_a2a or carries_identity
            if identity_claimed:
                trust_state = self.trust.classify(env, signature_ok=signature_ok)
                if trust_state != TrustState.KNOWN_PEER:
                    self.trust.quarantine_policy(env)
                    self._finish(env.event_id, "quarantined")
                    # karanténny obsah sa nikdy neposiela externe; operátor
                    # vidí sanitizovaný náhľad len v LOG kanáli.
                    return None
            elif not self.allow_plain_chat:
                self.trust.quarantine_policy(env)
                self._finish(env.event_id, "quarantined")
                return None

            # 5. state_machine.begin: idempotencia (KONS. #4) — raz a len raz
            if not self.state.begin(env):
                self._log(f"state_machine: duplicate event {env.event_id}, skipping")
                return None

            try:
                # 6. media_pipeline: shell-safe dekódovanie príloh (KONS. #10)
                attachment_text = self._process_attachments(env)

                # 7. VALIDÁCIA #2: detekcia výčitky/korekcie v tele správy ->
                #    apply_correction = TRVALÝ flag čítaný pred KAŽDÝM behom.
                for key, value in self.detect_corrections(env.body):
                    self.state.apply_correction(key, value,
                                                source_event_id=env.event_id)
                runtime_flags = self.state.flags()

                # 7b. FÁZA 6: correction learner — generalizuj výčitku na
                #     pravidlo v persona_profile (global alebo per-peer,
                #     perzistentné => prežíva restart; KONS #2 / backlog 8).
                peer_id = getattr(env, "sender", "") or "unknown"
                try:
                    learned = self.corrector.learn_from_message(peer_id, env.body)
                    if learned:
                        self._log(f"correction_learner: {peer_id} -> "
                                  f"{[c.key for c in learned]}")
                except Exception as exc:  # noqa: BLE001 — učenie nezabije tok
                    self._log(f"correction_learner error on {env.event_id}: {exc}")

                # 8. persona_hook: jazyk-mirror ako prvá inštrukcia (KONS. #6)
                system_prompt = self.persona.system_prompt(
                    env.body, Channel.CONTACT, runtime_flags)

                # 8b. FÁZA 6: inject persona profilu (GLOBAL anti-sycophancy/
                #     anti-korpo/limit + per-peer delta) pred LLM volanie.
                try:
                    lang = self.persona.detect_language(env.body or "")
                    self.persona_profile.set_language(peer_id, lang)
                    system_prompt = (system_prompt + "\n"
                                     + self.persona_profile.inject_prompt(peer_id)).strip()
                except Exception as exc:  # noqa: BLE001
                    self._log(f"persona_profile inject error: {exc}")

                # VALIDÁCIA #3: sanitize_content aj na akceptovanej KNOWN_PEER
                # ceste — telo správy (vrátane od trusted peera) je dáta, nie
                # inštrukcie; injection nemá cestu do LLM ako direktíva.
                user_text = self.trust.sanitize_content(env.body or "")
                if attachment_text:
                    user_text += "\n\n" + attachment_text

                # 9. LLM call (injektovaný)
                raw_reply: Optional[str] = None
                if self.llm_fn is not None:
                    raw_reply = self.llm_fn(system_prompt, user_text)
                if not raw_reply:
                    # žiadny LLM / prázdna odpoveď => krátka ack, nie román
                    raw_reply = "ok"

                target_channel = Channel.CONTACT if kind == SpaceKind.DM else Channel.GROUP

                # 10. VALIDÁCIA #8: style_check zapojený do pipeline —
                #     mechanické persona chyby (dash/korpo/bullets) oprav EŠTE
                #     pred output_filterom (filter je posledná línia, nie jediná).
                styled = self.persona.style_check(raw_reply, target_channel)
                if styled is not None:
                    raw_reply = styled

                # 11. output_filter: typová whitelist obálky von (KONS. #1 +
                #     VALIDÁCIA #4 origin-typing, #2 correction flags)
                outgoing = OutgoingMessage(
                    target=target_channel,
                    category="reply",
                    text=raw_reply,
                    reply_to_event_id=env.event_id,
                    origin="llm_reply",
                )
                filtered = self.output.filter(outgoing, runtime_flags=runtime_flags)

                # 12. REVALIDÁCIA #4 (ox nález): router.guard_outbound bol
                #     mŕtvy kód (nikdy nevolaný) — krytie KONS. #9 deklaroval
                #     audit, ale runtime ho nevykonával. Teraz je ZAPOJENÝ:
                #     A2A payload NIKDY neodchádza do GROUP/UNKNOWN priestoru.
                outbound = self.router.guard_outbound(
                    getattr(env, "space_id", "") or "",
                    payload_is_a2a=bool(env.is_a2a),
                    member_count=member_count,
                )
                if not outbound.allow:
                    self._log(f"router.guard_outbound DENY on {env.event_id}: "
                              f"{outbound.reason}")
                    self._finish(env.event_id, "dropped")
                    return None

                # 12b. send-once (quick-win 5): jediné odoslanie na event.
                #      Legitímna odpoveď odchádza do CONTACT (DM) AJ do GROUP
                #      (skupina) — output_filter už pre oba kanály vykonal
                #      rovnakú typovú kontrolu pôvodu (VALIDÁCIA #4), takže
                #      GROUP reply tu nespadne (funkčný regres ox nálezu:
                #      „krok 12 zahodí aj legitímne GROUP odpovede“).
                if filtered is None or filtered.target not in (
                        Channel.CONTACT, Channel.GROUP):
                    self._finish(env.event_id, "dropped")
                    return None
                if not self.output.assert_send_once(env.event_id):
                    self._log(f"output_filter: send-once block on {env.event_id}")
                    self._finish(env.event_id, "dropped")
                    return None

                # 12c. FÁZA 6: učenie z výmeny (peer delta) po úspešnom odoslaní.
                try:
                    self.persona_profile.update_from_exchange(
                        peer_id, env.body, filtered.text)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"persona_profile.update error: {exc}")

                self._finish(env.event_id, "sent")
                return filtered.text
            except Exception as exc:  # noqa: BLE001 — degradovať, nezabiť
                self._log(f"pipeline: processing error on {env.event_id}: {exc}")
                self._finish(env.event_id, "failed")
                return None
        except Exception as exc:  # noqa: BLE001 — posledná poistka
            self._log(f"pipeline: fatal error on {getattr(env, 'event_id', '?')}: {exc}")
            try:
                self._finish(getattr(env, "event_id", ""), "failed")
            except Exception:  # noqa: BLE001
                pass
            return None

    # ------------------------------------------------------------------
    # interné
    # ------------------------------------------------------------------

    def run_self_review(self, replies: List[str]):
        """FÁZA 6: explicitný self-review vlastných odpovedí.

        NEVOLÁ sa automaticky v handle() — periodicitu (napr. cron / po N
        odpovediach) rieši caller. Vracia self_review.ReviewResult
        (flags {sycophantic, corpo, too_long} + navrhované update profilu).
        """
        from .self_review import review_own_replies
        try:
            return review_own_replies(replies, profile=self.persona_profile)
        except Exception as exc:  # noqa: BLE001 — review nesmie zbúrať beh
            self._log(f"self_review error: {exc}")
            from .self_review import ReviewResult
            empty = ReviewResult()
            empty.flags = {"sycophantic": [], "corpo": [], "too_long": []}
            return empty

    @staticmethod
    def detect_corrections(text: Optional[str]) -> List[Tuple[str, object]]:
        """VALIDÁCIA #2: rozpoznaj výčitku/korekciu v texte od kontaktu.

        Vráti zoznam (key, value) párov pre state_machine.apply_correction.
        Deterministické regexy nad dôkazmi z incidentu; idempotentné —
        opakovaná detekcia rovnakej korekcie nič nerozbije.
        """
        body = text or ""
        found: List[Tuple[str, object]] = []
        for pattern, key, value in CORRECTION_RULES:
            if pattern.search(body):
                found.append((key, value))
        return found

    def _process_attachments(self, env: Envelope) -> str:
        """Dekóduj prílohy cez media_pipeline; sandbox blok => označený flag,
        nikdy tichý prázdny vstup (KONS. #10 + quick-win 4)."""
        parts: list[str] = []
        for att in getattr(env, "attachments", None) or []:
            att_path = att.get("path", "") if isinstance(att, dict) else ""
            att_kind = att.get("kind", "") if isinstance(att, dict) else ""
            result = (self.media.process_audio(att_path) if att_kind == "audio"
                      else self.media.process_video(att_path))
            if result.ok:
                parts.append(result.text)
            else:
                reply = self.media.undecoded_reply_policy(result)
                if reply:
                    parts.append(f"[media unavailable: {result.reason}]")
        return "\n".join(parts)

    def _finish(self, event_id: str, outcome: str) -> None:
        try:
            self.state.complete(event_id, outcome)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _log(message: str) -> None:
        print(f"[pipeline] {message}", file=sys.stderr)
