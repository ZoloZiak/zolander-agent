"""output_filter — whitelist toho, čo smie odísť do externého kanálu.

ADRESUJE (REPORT.md):
- KONSENZUS #1 „Leak interných vrstiev (progress/thinking/status) do externého DM"
  dôkaz: kontakt cituje interný string
  `' Redirected current run. I'll adjust using your correction.'` [46813:L4418].
- RIESENIA quick-win 1 [Output channel filter]: „potlačiť tool-progress, thinking
  tokens a interné status-stringy ... do externého kanálu; whitelist toho,
  čo smie ísť kontaktu".
- RIESENIA quick-win 5 [Stop send-then-redact]: „poslať finálnu odpoveď raz".
- KONSENZUS #6 (anti-korpobot): zákaz em-dash a korpo-šablóny v externom kanále.

Princíp: NIKDY nič neredaktovať po odoslaní. Filter beží PRED send() a je
jediným miestom, kde sa rozhoduje o obálke. Čo neprejde whitelistingom, ide
do Channel.LOG alebo OPERATOR, nikdy ku kontaktu.

VALIDÁCIA #4 (typová kontrola namiesto blacklistu): kategória správy sa
NEBERIE z parametra — odosielateľ si nesmie sám labelovať `category="reply"`.
Externý kanál povoli len správy s uznaným PÔVODOM (OutgoingMessage.origin),
ktorému prislúcha pevná kategória (EXTERNAL_ALLOWED_ORIGINS). Marker-zoznamy
ostávajú ako druhá línia obrany (depth-in-depth), primárne rozhodnutie je
typové: neznámy pôvod = LOG, bez výnimky.

VALIDÁCIA #2 (correction flagy): filter() prijíma runtime_flags zo
state_machine; flag `suppress_progress` spusti štrukturálnu kontrolu
progress-vzoriek (nielen hardcoded fráz).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .types import Channel, OutgoingMessage


class OutputFilter:
    """Jediný bod, cez ktorý prechádza každá odchádzajúca správa.

    Plne deterministický — žiadne I/O, žiadny random, testovateľný bez mockov.
    """

    #: VALIDÁCIA #4: whitelist PÔVODU -> kategória pre externé kanály.
    #: Jediný uznaný pôvod externej správy je "llm_reply" (výstup LLM po
    #: persona/style vrstve, konštruovaný výhradne v pipeline). Čokoľvek iné
    #: (alebo bez origin) je nepoučiteľné a ide do LOG.
    EXTERNAL_ALLOWED_ORIGINS = {
        "llm_reply": "reply",
    }

    #: interné status frázy — DRUHÁ línia obrany (primárna je typová kontrola
    #: pôvodu vyššie). Dôkaz [46813:L4418]: kontakt citoval
    #: `' Redirected current run...'`
    INTERNAL_STATUS_MARKERS = (
        "Redirected current run",
        "[CONTEXT COMPACTION]",
        "self-verify:",
        "api_calls=",
        "time=",
        "tokens_used=",
        "response=",
    )

    #: znaky/frázy zakázané v externom registri (anti-korpobot, KONSENZUS #6)
    EXTERNAL_BANNED_PATTERNS = ("—", "\u2013", "V rámci ", "Dôležité rozlíšenie:")

    #: korpo frázy — ak sú v texte pre externý kanál, presmeruje sa do LOG
    CORPO_PHRASES = (
        "dovoľte mi",
        "radi Vám",
        "s potešením Vám",
        "neváhajte kontaktovať",
        "ďakujeme za pochopenie",
    )

    #: VALIDÁCIA #2: štrukturálne progress vzory (nie hardcoded frázy) —
    #: aktivujú sa flagom suppress_progress zo state_machine korekcií.
    _PROGRESS_RE = re.compile(
        r"(?i)\bapi_calls\b|\btokens_used\b|\bstep\s+\d+\s*/\s*\d+\b"
        r"|\d+\s*%\s*(done|hotovo|complete[d]?)\b|\belapsed\b\s*\d+"
    )

    #: interná cesta /Users/<user> — nikdy externe (gemini: repo sanitizácia)
    _HOME_PATH_RE = re.compile(r"/Users/[A-Za-z0-9_.\-]+")

    #: fingerprint = 64 hex znakov — nikdy externe
    _FINGERPRINT_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

    def __init__(self) -> None:
        self._sent_event_ids: set[str] = set()

    def filter(self, msg: OutgoingMessage,
               runtime_flags: Optional[Dict[str, Any]] = None) -> Optional[OutgoingMessage]:
        """Rozhodni, či `msg` smie odísť. Vráti (prípadne upravenú) správu alebo None.

        Pravidlá (v poradí):
          1. target == OPERATOR/LOG -> prepustiť všetko (veducko vidí aj interné).
          2. target CONTACT/GROUP + neuznaný/chýbajúci origin (VALIDÁCIA #4:
             typová kontrola; sender si nemôže self-labelovať category)
             -> presmerovať do LOG.
          3. target CONTACT/GROUP + flag suppress_progress (VALIDÁCIA #2) +
             progress vzor v texte -> presmerovať do LOG.
          4. target CONTACT/GROUP + interný marker/fingerprint//Users cesta
             -> presmerovať do LOG (leak vektor [46813:L4418]).
          5. target CONTACT/GROUP + em/en-dash -> preformátovať (em-dash na
             "; ", en-dash na "-") a vrátiť upravenú správu.
          6. target CONTACT/GROUP + korpo fráza -> presmerovať do LOG
             (nedá sa bezpečne preformátovať automaticky; anti-korpobot #6).
          7. Inak prepustiť.

        Tichá degradácia: pri chybe na vstupe vráti None (nikdy nevystrelí
        výnimku do pipeline — fail-safe podľa BRIEF pravidlo 3).
        """
        try:
            if not isinstance(msg, OutgoingMessage):
                return None
            # 1. OPERATOR/LOG vidí všetko
            if msg.target in (Channel.OPERATOR, Channel.LOG):
                return msg

            if msg.target in (Channel.CONTACT, Channel.GROUP):
                # 2. VALIDÁCIA #4: kategória z pôvodu, nie z parametra.
                effective = self.EXTERNAL_ALLOWED_ORIGINS.get(msg.origin or "")
                if effective is None:
                    return self._redirect_to_log(
                        msg,
                        f"untrusted origin {msg.origin!r}: category cannot be self-labelled",
                    )
                if msg.category != effective:
                    return self._redirect_to_log(
                        msg,
                        f"category {msg.category!r} contradicts origin "
                        f"{msg.origin!r} (expected {effective!r})",
                    )

                # 3. VALIDÁCIA #2: correction flagy zo state_machine
                flags = runtime_flags or {}
                if flags.get("suppress_progress") and self._PROGRESS_RE.search(msg.text):
                    return self._redirect_to_log(
                        msg, "suppress_progress correction: progress pattern in text")

                # 4. interné markery / fingerprinty / home cesty -> LOG
                for marker in self.INTERNAL_STATUS_MARKERS:
                    if marker in msg.text:
                        return self._redirect_to_log(msg, f"internal marker: {marker!r}")
                if self._FINGERPRINT_RE.search(msg.text):
                    return self._redirect_to_log(msg, "fingerprint in external text")
                if self._HOME_PATH_RE.search(msg.text):
                    return self._redirect_to_log(msg, "local path in external text")

                # 5. pomlčky -> preformátovať (anti-korpobot [46813:L4223])
                text = self._strip_dashes(msg.text)

                # 6. korpo frázy -> LOG (nemôžu ísť von)
                lowered = text.lower()
                for phrase in self.CORPO_PHRASES:
                    if phrase.lower() in lowered:
                        return self._redirect_to_log(msg, f"corpo phrase: {phrase!r}")

                if text != msg.text:
                    return OutgoingMessage(
                        target=msg.target,
                        category=msg.category,
                        text=text,
                        reply_to_event_id=msg.reply_to_event_id,
                        origin=msg.origin,
                    )
                return msg

            # neznámy kanál -> fail-closed: nič neodchádza
            return self._redirect_to_log(msg, f"unknown channel: {msg.target}")
        except Exception:  # noqa: BLE001 — fail-safe, nikdy nezabiť pipeline
            return None

    def assert_send_once(self, event_id: str) -> bool:
        """Garantuj jediné finálne odoslanie na jeden spracovaný event.

        Adresuje quick-win 5 [Stop send-then-redact]: redacted $... cyklus
        [46138]/[46817]. Prvé volanie pre event_id vráti True a rezervuje
        slot; každé ďalšie volanie pre ten istý event vráti False skôr,
        než duplicitná odpoveď opustí systém.

        Deterministické; rezervácia je nevratná (send-once ledger).
        """
        if not event_id:
            return False
        if event_id in self._sent_event_ids:
            return False
        self._sent_event_ids.add(event_id)
        return True

    # ------------------------------------------------------------------
    # interné
    # ------------------------------------------------------------------

    def _redirect_to_log(self, msg: OutgoingMessage, reason: str) -> OutgoingMessage:
        """Presmeruj správu do auditného LOG kanála namiesto externého cieľa."""
        return OutgoingMessage(
            target=Channel.LOG,
            category=msg.category,
            text=f"[blocked->log] ({reason}) {msg.text}",
            reply_to_event_id=msg.reply_to_event_id,
            origin=msg.origin,
        )

    @staticmethod
    def _strip_dashes(text: str) -> str:
        """Preformátuj em-dash (—) a en-dash (–) na neutrálnu interpunkciu."""
        text = text.replace(" — ", "; ").replace("—", ", ")
        text = text.replace(" – ", " - ").replace("\u2013", "-")
        return text
