"""correction_learner — detekcia výčitky -> generalizácia -> trvalé pravidlo.

FÁZA 6. ADRESUJE (REPORT.md):
- KONSENZUS #2 „Korekcia sa nepremietne do runtime správania“: prvá výčitka
  *„no i po nevhodne mi wyswietlasz co robisz XD“* [46813:L4210 / 20:02:09],
  o ~40 min identická [L4413]. [gpt55]: „korekcia v jednom turne ≠ zmena
  systému“.
- RIESENIA backlog 8 [Correction persistence]: korekcia sa musí premietnuť
  do runtime stavu, nielen do textu odpovede.

Princíp: výčitka od kontaktu sa NIE JE verbálne uznať — zovšeobecní sa na
pravidlo (key + inštrukcia) a zapíše cez PersonaProfile.add_learned_rule()
do JSON perzistencie => prežíva restart. Scope: všeobecné správanie
(interné leacky, korpo tón, dĺžka) ide do GLOBAL; veci viazané na konkrétneho
kontakta (jazyk, register) do PER_PEER profilu.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .persona_profile import PersonaProfile


@dataclass
class LearnedCorrection:
    key: str                 # stabilný kľúč pravidla (idempotencia)
    instruction: str         # text do promptu
    scope: str               # "global" | "peer"
    trigger_quote: str       # čo to spustilo (auditná stopa)


# Generalizačná tabuľka: pattern -> (key, instruction, scope).
# Prvý riadok = reálny dôkaz incidentu [46813:L4210].
GENERALIZATIONS: Tuple[Tuple[re.Pattern, str, str, str], ...] = (
    # progress/thinking/status nemajú ísť ku kontaktu (KONS #1/#2)
    (re.compile(r"(?i)\bwyswietlasz\b|\bwyswietla[sś]\b|\bzobrazuj\w*\b"),
     "suppress_progress",
     "Žiadny interný progress/thinking/status text do odpovede. "
     "Kontakt vidí len finálnu repliku.",
     "global"),
    (re.compile(r"(?i)\bpresta[nň]\b.*\b(posiel|zobraz|pisat|písať)"),
     "suppress_progress",
     "Žiadny interný progress/thinking/status text do odpovede.",
     "global"),
    # korpo tón (KONS #6: „jak korpobot i do tego z emdashami“)
    (re.compile(r"(?i)\bkorpobot\w*|\bcorpo\s?bot\b|\bemdash\w*|\bem-?das[hž]\w*"),
     "no_corpo_reinforced",
     "Tvrdý zákaz korpo fráz a em-dash (—): krátke vety, ľudský tón.",
     "global"),
    # jazyk („naucz sie nevhodne po polsku pisac“)
    (re.compile(r"(?i)\b(pisz|pi[sš])\b.*\bpo polsku\b|\bspeak polish\b"
                r"|\bpo polsku\b"),
     "force_polish",
     "Odpovedaj VÝHRADNE po poľsky.",
     "peer"),
    # dĺžka/narrrácia („zadna nevhodne narrracja tylko“, KONS #8)
    (re.compile(r"(?i)\bnarracj\w*|\bnarrracja\b|\brom[aá]n\b|\bdluguje[sś]\b"
                r"|\bkrócej\b|\bkrocej\b|\bshorter\b"),
     "be_brief",
     "Žiadna narratíva ani monológ. Odpoveď max pár slov/viet.",
     "peer"),
)

# Fallback: silná výčitka bez šablóny -> peer-scoped ad-hoc pravidlo.
GENERIC_REPROACH_RE = re.compile(
    r"(?i)(co\s+(ty\s+)?robisz\s+zle|co\s+robisz|what.*doing\s+wrong"
    r"|robisz\s+źle|rob[ií][sš]\s+zle|stop\s+(it|doing)|dosta[nň]\b)"
)


def detect_reproaches(text: str) -> List[LearnedCorrection]:
    """Deterministicky rozpoznané korekcie v texte. Idempotentné —
    rovnaká výčitka dáva rovnaký key (opakovaný zápis nič nerozbije)."""
    body = text or ""
    found: List[LearnedCorrection] = []
    for pattern, key, instruction, scope in GENERALIZATIONS:
        m = pattern.search(body)
        if m:
            found.append(LearnedCorrection(key, instruction, scope,
                                           trigger_quote=m.group(0)))
    if not found and GENERIC_REPROACH_RE.search(body):
        m = GENERIC_REPROACH_RE.search(body)
        found.append(LearnedCorrection(
            "learned_generic_reproach",
            "Kontakt signalizoval všeobecnú nespokojnosť — skrátiť odpoveď "
            "a opýtať sa priamo, čo konkrétne opraviť.",
            "peer", trigger_quote=m.group(0)))
    return found


class CorrectionLearner:
    """Zapisuje generalizované korekcie do PersonaProfile (perzistentné)."""

    def __init__(self, profile: PersonaProfile) -> None:
        self.profile = profile
        self.last_learned: List[LearnedCorrection] = []

    def learn_from_message(self, peer_id: str, text: Optional[str]
                           ) -> List[LearnedCorrection]:
        """Deteguj výčitky v inbound správe a zapiš pravidlá.

        Vráti zoznam naozaj NOVO zapísaných korekcií (duplicitný key sa
        nezapisuje znova). Korekcia je hneď perzistentná (save vnútri
        add_learned_rule) => prežíva restart.
        """
        applied: List[LearnedCorrection] = []
        for corr in detect_reproaches(text or ""):
            already = (self.profile.has_rule(corr.key)
                       if corr.scope == "global"
                       else self.profile.has_rule(corr.key, peer_id=peer_id))
            if already:
                continue
            self.profile.add_learned_rule(
                corr.key, corr.instruction,
                peer_id=None if corr.scope == "global" else peer_id)
            applied.append(corr)
        self.last_learned = applied
        return applied
