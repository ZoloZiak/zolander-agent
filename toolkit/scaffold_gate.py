#!/usr/bin/env python3
"""scaffold_gate.py — ZÁMOK ZÁPISU proti vate (Neuromancer scaffolding pravidlo).

PREČO (2026-09-01):
  Spike 010 (VALIDATED, κ 0.60 cross-lab) dokázal, že epistemická os
  explicit/deductive JE reprodukovateľná — nie je to model-šum ako Z1.
  Abstrakčný engine generoval vatu, lebo zapisoval odvodené "princípy" (rakovinový
  L3), ktoré NENIESLI premisy a NEDALI sa dohľadať. Fréchet mean → Opus pomenuje
  → zápis, žiadne ODMIETNUTIE.

  Neuromancer XR pravidlo (verbatim z blogu Plastic Labs):
    "Záver sa smie stavať LEN na záveroch vyššej [/rovnej] istoty, a MUSÍ niesť
     svoje premisy."

  Toto je to pravidlo ako MECHANIZMUS ODMIETNUTIA pri zápise — NIE nová vrstva
  pamäte (L0-L3 je ortogonálna os trvanlivosti, spike 010 verdikt), NIE LLM na
  horúcej ceste (deterministické, lacné, overiteľné pri zdroji).

MODEL:
  Každý záznam nesie `certainty` (ak chýba → 'explicit', spätná kompatibilita).
  - explicit  = doslovne uvedený fakt → ACCEPT vždy (netreba premisy).
  - deductive = nutne plynie z premís → MUSÍ mať `premises` (list id), KAŽDÁ:
      (a) dohľadateľná (resolver ju nájde v pamäti), inak REFUSED;
      (b) istota >= istota záveru (scaffolding: nestaviame isté na neistom).
  - inductive/abductive = ZATIAĽ nepodporované na zápis cez tento gate
      (spike 006 ukázal, že derivácia týchto na 405 zázn. škodí; Neuromancer ich
      odkladá do MR). Ak ich niekto pošle ako certainty záveru → REFUSED
      (kým nie je spike, čo ich validuje). Ako PREMISA sú tiež príliš nízke.
  - neznámy certainty → REFUSED (nie tiché prepustenie).

  Najslabší článok rozhoduje: jedna premisa pod prahom = celý záver REFUSED.

KILL-SWITCH (aktívne s vypínačom, nie mŕtvy opt-in flag):
  ZOL_SCAFFOLD_GATE=0  → gate prepustí čokoľvek (ACCEPT, reason='kill-switch').

Použitie (v cmd_remember, PRED zápisom):
  from scaffold_gate import evaluate, ACCEPT
  dec, reason = evaluate(obj, resolver)   # resolver(premise_id) -> meta|None
  if dec != ACCEPT: odmietni zápis, vráť {"refused": reason}
"""
import os

ACCEPT = "ACCEPT"
REFUSED = "REFUSED"

# Rebrík istoty: vyššie číslo = vyššia istota. Záver sa smie oprieť len o
# premisu s istotou >= vlastnej. Explicit je najistejší (doslovný fakt).
CERTAINTY_RANK = {
    "explicit": 3,
    "deductive": 2,
    "inductive": 1,
    "abductive": 0,
}

# Ktoré istoty smie tento gate PRIJAŤ ako certainty ZÁVERU pri zápise.
# inductive/abductive odložené (spike 006 = škodia na tejto škále; Neuromancer MR).
WRITABLE = {"explicit", "deductive"}

DEFAULT_CERTAINTY = "explicit"


def _norm(obj):
    """Vytiahni certainty (default explicit) a premises (list) z objektu."""
    c = (obj.get("certainty") or DEFAULT_CERTAINTY).strip().lower()
    prem = obj.get("premises") or []
    if not isinstance(prem, list):
        prem = [prem]
    return c, prem


def evaluate(obj, resolver):
    """Rozhodni ACCEPT/REFUSED pre jeden zápisový objekt.

    obj: dict aspoň s 'text'; voliteľne 'certainty', 'premises'.
    resolver: callable(premise_id) -> meta dict s 'certainty' | None ak nenájdené.
    Návrat: (rozhodnutie, dôvod:str).
    """
    # Kill-switch: aktívny gate s vypínačom.
    if os.environ.get("ZOL_SCAFFOLD_GATE") == "0":
        return ACCEPT, "kill-switch: ZOL_SCAFFOLD_GATE=0 (gate vypnutý)"

    certainty, premises = _norm(obj)

    # Neznámy certainty = REFUSED (nie tiché prepustenie).
    if certainty not in CERTAINTY_RANK:
        return REFUSED, f"neznámy certainty {certainty!r} (dovolené: {sorted(CERTAINTY_RANK)})"

    # Nezapisovateľná istota ako certainty záveru (inductive/abductive odložené).
    if certainty not in WRITABLE:
        return REFUSED, (f"certainty {certainty!r} sa zatiaľ nezapisuje cez scaffold "
                         f"gate (spike 006: škodí na tejto škále; Neuromancer MR odklad)")

    concl_rank = CERTAINTY_RANK[certainty]

    # Explicit = doslovný fakt, netreba premisy → ACCEPT.
    if certainty == "explicit":
        return ACCEPT, "explicit fakt: zapísaný bez premís"

    # Deductive: MUSÍ mať aspoň jednu premisu.
    if not premises:
        return REFUSED, ("deductive záver bez premís = vata; scaffolding vyžaduje "
                         "aspoň jednu dohľadateľnú premisu")

    # Každá premisa: dohľadateľná + istota >= istota záveru (najslabší článok).
    for pid in premises:
        meta = resolver(pid)
        if meta is None:
            return REFUSED, (f"premisa {pid} sa nedá dohľadať v pamäti — "
                             f"záver nesmie visieť vo vzduchu")
        p_cert = (meta.get("certainty") or DEFAULT_CERTAINTY).strip().lower()
        p_rank = CERTAINTY_RANK.get(p_cert, -1)
        if p_rank < concl_rank:
            return REFUSED, (f"premisa {pid} má istotu {p_cert!r} (rank {p_rank}) "
                             f"< záver {certainty!r} (rank {concl_rank}) — nestaviam "
                             f"istejší záver na neistejšej premise")

    return ACCEPT, f"deductive záver stojí na {len(premises)} dohľadateľných premisách"


if __name__ == "__main__":
    # Sebademo: prejdi troma prípadmi.
    store = {1: {"certainty": "explicit"}, 2: {"certainty": "inductive"}}
    r = lambda i: store.get(i)  # noqa: E731
    for obj in [
        {"text": "PESEL 123", "certainty": "explicit"},
        {"text": "vata", "certainty": "deductive"},
        {"text": "dobrý záver", "certainty": "deductive", "premises": [1]},
        {"text": "zlý základ", "certainty": "deductive", "premises": [2]},
    ]:
        print(evaluate(obj, r), "<-", obj)
