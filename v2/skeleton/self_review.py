"""self_review — deterministický audit vlastných odpovedí.

FÁZA 6. ADRESUJE (REPORT.md):
- KONS #6: korpo tón/em-dash (*„bez prazdnych korporatnych fraz“*
  [46813:L4223]) -> flag `corpo`.
- KONS #8: dlhé odpovede na krátky vstup (*„zadna nevhodne narrracja tylko“*
  [46813:L4256]) -> flag `too_long` (limit z GLOBAL_PROFILE.max_reply_chars).
- CONTACT_SOLUTIONS A1/A2: anti-sycophancy — podlizujúci súhlas bez opory
  („máš úplnú pravdu“) -> flag `sycophantic`.

API: review_own_replies(replies, profile=None, llm_fn=None) -> ReviewResult
(flags {sycophantic, corpo, too_long} + suggested_profile_updates).
LLM je VOLITELNÝ (injektovaný fn); základ je vždy deterministická heuristika,
takže review beží offline a opakovateľne (BRIEF pravidlo 1). Periodicitu
volania rieši caller (pipeline ju nevolá automaticky).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .persona_profile import PersonaProfile


@dataclass
class ReplyFinding:
    index: int                 # index odpovede v zozname
    reason: str                # čo konkrétne zaváňa
    quote: str = ""            # spúšťací úsek (auditná stopa)


@dataclass
class ReviewResult:
    flags: Dict[str, List[ReplyFinding]] = field(default_factory=dict)
    suggested_profile_updates: List[Dict[str, object]] = field(default_factory=list)
    llm_notes: List[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(self.flags.values())


#: súhlasné/sychophant frázy — flag len keď stoja BEZ opory v texte
_SYCOPHANT_PATTERNS = (
    re.compile(r"(?i)\bm[áa][sšt][eé]?\s+[uú]?p[lľ]n[uúeé]?\s*pravd\w*"),
    re.compile(r"(?i)\bm[áa][sšt][eé]?\s+pravdu\b"),
    re.compile(r"(?i)(you'?re|you are)\s+(absolutely|completely|totally)\s+right"),
    re.compile(r"(?i)(great|excellent|amazing|brilliant)\s+(question|point|observation)"),
    re.compile(r"(?i)v[yý]born[áa]\s+(ot[aá]zka|postreh)"),
    re.compile(r"(?i)\b(absol[uút]n[eě]|u[pp]ln[eě])\s+souhlas[ií]m\b"
               r"|\b(u[pp]lne|absol[uút]ne)\s+s[uú]hlas[ií]m\b"),
)

_CORPO_RE = re.compile(
    r"(?i)dovo[lľ]te mi|radi v[áa]m|s pote[sš]en[ií]m v[áa]m|nev[aá]hajte "
    r"kontaktova|ďakujeme za pochopenie|v r[áa]mci|pros[ií]m, berte na vedomie"
    r"|allow me to|we are pleased|i trust this message finds")
_EM_DASH_RE = re.compile(r"—|\u2013")


def _has_supporting_evidence(reply: str) -> bool:
    """Súhlasná fráza s oporou (číslo/dôvod za ňou) nie je sycophancy."""
    # ak replika obsahuje dôvod/argument po fráze (číslica alebo 'lebo/pre/because'),
    # považujeme súhlas za oporený
    return bool(re.search(
        r"(?i)(lebo|preto|because|\d)", reply))


def review_own_replies(replies: List[str],
                       profile: Optional[PersonaProfile] = None,
                       llm_fn: Optional[Callable[[str], str]] = None
                       ) -> ReviewResult:
    """Zhodnoť zoznam vlastných odpovedí.

    replies: odchádzajúce texty (Channel.CONTACT/GROUP) na review.
    profile: pre max_reply_chars; None => default 480.
    llm_fn: voliteľný hĺbkový reviewer (text -> note); heuristika beží vždy.

    Vracia ReviewResult; nikdy nevyhodí výnimku von.
    """
    result = ReviewResult()
    result.flags = {"sycophantic": [], "corpo": [], "too_long": []}
    max_chars = 480
    if profile is not None:
        try:
            max_chars = int(profile.global_.max_reply_chars)
        except Exception:  # noqa: BLE001
            pass

    for i, reply in enumerate(replies or []):
        text = reply or ""
        for pat in _SYCOPHANT_PATTERNS:
            m = pat.search(text)
            if m and not _has_supporting_evidence(text):
                result.flags["sycophantic"].append(ReplyFinding(
                    i, "podlizujúci súhlas bez opory", quote=m.group(0)))
                break
        cm = _CORPO_RE.search(text)
        if cm:
            result.flags["corpo"].append(ReplyFinding(
                i, "korpo fráza", quote=cm.group(0)))
        elif _EM_DASH_RE.search(text):
            result.flags["corpo"].append(ReplyFinding(
                i, "em/en-dash vo vetách", quote="—"))
        if len(text) > max_chars:
            result.flags["too_long"].append(ReplyFinding(
                i, f"{len(text)} znakov > limit {max_chars}",
                quote=text[:40]))

    if llm_fn is not None:
        for i, reply in enumerate(replies or []):
            try:
                note = llm_fn(reply or "")
                if note:
                    result.llm_notes.append(f"[{i}] {note}")
            except Exception as exc:  # noqa: BLE001 — LLM je voliteľný
                result.llm_notes.append(f"[{i}] llm_fn error: {exc}")

    result.suggested_profile_updates = _suggest_updates(result, profile, max_chars)
    return result


def _suggest_updates(result: ReviewResult, profile: Optional[PersonaProfile],
                     max_chars: int) -> List[Dict[str, object]]:
    """Navrhni zmeny profilu (NEROBÍ ich sám — rozhoduje caller/operator)."""
    updates: List[Dict[str, object]] = []
    if result.flags["too_long"]:
        updates.append({
            "scope": "global", "key": "max_reply_chars",
            "value": max(120, int(max_chars * 0.7)),
            "reason": f'{len(result.flags["too_long"])} odpovedí nad limit',
        })
    if result.flags["sycophantic"]:
        updates.append({
            "scope": "global", "key": "no_comfort_agreement",
            "value": "REINFORCE: žiadny súhlas bez faktickej opory.",
            "reason": f'{len(result.flags["sycophantic"])} '
                      f"podlizujúcich odpovedí",
        })
    if result.flags["corpo"]:
        updates.append({
            "scope": "global", "key": "no_corpo",
            "value": "REINFORCE: korpo frázy a em-dash zakázané.",
            "reason": f'{len(result.flags["corpo"])} korpo nálezov',
        })
    return updates
