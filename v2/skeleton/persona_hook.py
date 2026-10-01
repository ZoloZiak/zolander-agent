"""persona_hook — jazyk-mirror register + anti-korpobot vrstva.

ADRESUJE (REPORT.md):
- KONSENZUS #6 „Persona/jazyk mismatch (poľština, korpo-tón, em-dash)":
  `naucz sie nevhodne po polsku pisac` [46813:L4217], `a nie nevhodne jak
  korpobot i do tego z emdashami` [46813:L4223]. [gpt55]: „mirroring bol
  povrchový (preklad), nie sociálny register".
- RIESENIA backlog 9 [Persona/language hook]: „reálny register-mirroring
  (slang, rytmus, stručnosť), zákaz em-dash a korpo-šablóny".
- BRIEF hard requirement 1: jazykové zrkadlenie ako PRVÁ inštrukcia.
- BRIEF hard requirement 5: Zolander ≠ ZoloZiak; „vedúcko" len pre veducka;
  súkromné detaily operátora nikdy externe.
- UNIKATNY NALEZ [gpt55]: zámena kontakt ≠ jeho agent —
  `that agent is not me` [46813:L4195] vs agentovo
  `(contact vs their agent)` [46052]. Kontakt a jeho agent = dve entity.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional

from .types import Channel


class PersonaHook:
    """Vkladá persona pokyny pred LLM call a kontroluje výstup."""

    #: heuristika: diakritické znaky per jazyk (BRIEF: heuristika stačí)
    _LANG_CHARS = {
        "pl": set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"),
        "cs": set("ěščřžýáíéůúĚŠČŘŽÝÁÍÉŮÚďťňĎŤŇ"),
        "sk": set("ľščťžýáíéúäôňĽŠČŤŽÝÁÍÉÚÄÔŇ"),
        "de": set("äöüßÄÖÜ"),
    }
    _LANG_WORDS = {
        "pl": ("nie", "jest", "się", "to", "nevhodne", "wyswietlasz", "pisać",
               "jak", "ale", "tylko", "dobra", "no"),
        "cs": ("je", "to", "se", "ale", "pro", "jako", "dobře", "jo"),
        "sk": ("je", "sa", "ale", "pre", "ako", "dobre", "hej", "no"),
        "en": ("the", "you", "is", "are", "and", "what", "ok", "hey"),
    }

    #: korpo frázy (KONSENZUS #6) — v externom registri zakázané
    CORPO_PHRASES = (
        "dovoľte mi", "radi vám", "s potešením vám", "neváhajte kontaktovať",
        "ďakujeme za pochopenie", "v rámci", "prosím, berte na vedomie",
        "dôležité rozlíšenie", "allow me to", "we are pleased",
    )

    def build_instruction(self, contact_language: str,
                          target: Channel,
                          runtime_flags: Optional[Dict[str, object]] = None) -> str:
        """Vráti persona blok pre LLM. Poradie je závazné:
          1. JAZYK: odpovedaj v jazyku protistrany (PRVÁ inštrukcia, nie
             pochovaná odrážka — priama lekcia KONSENZUS #6).
          2. REGISTER: mirroruj slang/rytmus/stručnosť; krátko ako človek
             na mobile; žiadna narratíva na krátky vstup (quick-win 3).
          3. ANTI-KORPOBOT: zákaz em-dash (—), zákaz korpo fráz, žiadne
             odrážkové vysvetľovacie bloky.
          4. IDENTITA: si Zolander, nie ZoloZiak; oslovenie „vedúcko"
             VÝHRADNE pre veducka (Channel.OPERATOR); externému kontaktu
             neprezrádzaj súkromné detaily operátora; kontakt ≠ jeho agent
             (the contact ≠ the contact's agent) — adresuj osobu, nie jej agenta.

        `runtime_flags` sú korekcie zo state_machine.get_flag()/flags()
        (KONSENZUS #2): napr. suppress_progress=True pridá príkaz netlačiť
        interný progress do odpovede.
        """
        lang_map = {
            "pl": "poľsky (polski)",
            "cs": "česky",
            "sk": "po slovensky",
            "en": "anglicky",
            "unknown": "neutrálny krátky EN",
        }
        lang_name = lang_map.get(contact_language, f"jazyku {contact_language}")
        flags = runtime_flags or {}

        lines = [
            f"1. JAZYK: Odpovedaj výhradne {lang_name}. "
            f"Toto je najdôležitejšie pravidlo tohto turnu.",
            "2. REGISTER: Píš krátko, ako človek na mobile. Mirroruj register "
            "protistrany (slang/rytmus/stručnosť). Žiadna narratíva ani monológ "
            "na krátky či prázdny vstup.",
            "3. ANTI-KORPOBOT: Zakázaný em-dash (—), en-dash vo vetách, korpo "
            "frázy („dovoľte mi“, „radi Vám“, „s potešením Vám“) a odrážkové "
            "vysvetľovacie bloky. Maximálne pár viet.",
            "4. IDENTITA: Si Zolander, nie ZoloZiak. Oslovenie „vedúcko“ patrí "
            "výhradne veduckej (interný operátor). Externému kontaktu nikdy "
            "neprezrádzaj súkromné detaily operátora. Kontakt a jeho agent sú "
            "dve odlišné entity — adresuj osobu, nie jej agenta.",
        ]
        if flags.get("suppress_progress"):
            lines.append(
                "5. KOREKCIA (TRVALÁ): žiadny interný progress/thinking/status "
                "text do odpovede. Toto je uložená korekcia, platí každý turn."
            )
        return "\n".join(lines)

    def detect_language(self, text: str) -> str:
        """Deteguj jazyk prichádzajúceho textu (pl/cs/sk/en/de).

        Heuristika: diakritika + frekvencia typických slov. Lekcia z UNIKATNEHO
        NÁLEZU [opus]: chybná klasifikácia dekódu (perzsko-arabský text označený
        za čínštinu) — pri neistote/mimo latiniky vráti 'unknown' (=> neutrálny
        krátky EN, nie halucinovaný mirror).
        """
        text = text or ""
        if not text.strip():
            return "unknown"

        non_latin = sum(
            1 for ch in text
            if unicodedata.category(ch).startswith("L")
            and not ("a" <= ch.lower() <= "z")
            and ch not in "".join("".join(s) for s in self._LANG_CHARS.values())
        )
        letters = sum(1 for ch in text if unicodedata.category(ch).startswith("L"))
        if letters == 0:
            return "unknown"
        if non_latin / max(letters, 1) > 0.15:
            return "unknown"  # mimo latiniky => nepoznáme, fail-safe

        lowered = text.lower()
        scores: Dict[str, float] = {lang: 0.0 for lang in
                                    ("pl", "cs", "sk", "en", "de")}
        for lang, chars in self._LANG_CHARS.items():
            hits = sum(1 for ch in text if ch in chars)
            scores[lang] += hits * 2.0
        words = re.findall(r"[a-ząćęłńóśźżäöüßáčíéůťďň]+", lowered)
        for lang, markers in self._LANG_WORDS.items():
            scores[lang] += sum(1 for w in words if w in markers)

        best = max(scores, key=lambda k: scores[k])
        if scores[best] <= 0:
            return "en"  # čistá ASCII angličtina bez markerov => default
        return best

    def style_check(self, text: str, target: Channel) -> Optional[str]:
        """Posledná kontrola štýlu pred output_filter.

        Opravuje: em/en-dash, korpo frázy, odrážkové monobloky (>5 po sebe
        idúcich odrážok zredukuje na prose). Vráti opravený text alebo None
        ak je text v poriadku.
        """
        if target == Channel.LOG:
            return None  # log nemusí spĺňať externý štýl
        fixed = text or ""
        original = fixed

        fixed = fixed.replace(" — ", "; ").replace("—", ", ")
        fixed = fixed.replace(" – ", " - ").replace("\u2013", "-")

        lowered = fixed.lower()
        for phrase in self.CORPO_PHRASES:
            if phrase.lower() in lowered:
                # vyhoď celú vetu s korpo frázou (anti-korpobot #6)
                pattern = re.compile(r"[^.!?]*" + re.escape(phrase) + r"[^.!?]*[.!?]?",
                                     re.IGNORECASE)
                fixed = pattern.sub("", fixed)
                lowered = fixed.lower()
        fixed = re.sub(r"  +", " ", fixed).strip()

        bullets = re.findall(r"(?:^|\n)\s*[-•*]\s+", fixed)
        if len(bullets) >= 5:
            fixed = re.sub(r"(?:^|\n)\s*[-•*]\s+", "; ", fixed)

        return None if fixed == original.strip() and fixed == original else (fixed or "")

    # praktická pomôcka pre pipeline: hotový system prompt pre turn
    def system_prompt(self, incoming_text: str, target: Channel,
                      runtime_flags: Optional[Dict[str, object]] = None) -> str:
        """detect_language + build_instruction v jednom kroke."""
        lang = self.detect_language(incoming_text)
        return self.build_instruction(lang, target, runtime_flags)
