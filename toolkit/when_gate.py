#!/usr/bin/env python3
"""when_gate.py — ŽL5 temporálny prefilter (kolo31, ŽL cesta zo scout backlogu).

Zapína sa LEN keď query_router klasifikuje dotaz ako route="temporal"
("aká je AKTUÁLNA adresa", "posledný stav X", "kde teraz bývam"). Vtedy má
zmysel tvrdo potlačiť superseded (neaktuálne) záznamy — na otázku o aktuálnosti
nechceme vrátiť fakt, ktorý bol medzičasom nahradený, aj keby mal vyššie
recall skóre.

Vzťah k StateMem (2608.19652): current-state filter už existuje v recall-e ako
mäkký/vždy-zapnutý mechanizmus. Toto je jeho DOTAZOVO-PODMIENENÝ, tvrdý variant:
hard-drop superseded LEN keď sa používateľ pýta na aktuálnosť. Pri bežnom
point dotaze môže byť historický fakt legitímny (napr. "kde býval predtým").

Dizajn (rovnaká disciplína ako graph_expand / router):
  - route != "temporal"  → NO-OP, kandidáti prejdú nedotknutí (poradie zachované)
  - prázdny/chýbajúci temporal stav → FAIL-OPEN (nefiltruj — nemáme dôkaz)
  - id bez temporal záznamu → považuj za aktívny (prejde)
  - nič sa nemaže z pamäte; len sa NEVRÁTI do tohto recall výsledku (reverzibilné)
"""


def when_gate(candidates, temporal_state, route="point", return_dropped=False):
    """Prefilter recall kandidátov podľa bitemporal stavu.

    Args:
      candidates: list dictov s aspoň {"id": ...}. Poradie sa zachováva.
      temporal_state: {id: {"valid_until": ..., "superseded_by": ...}} — z
                      zol_graph._temporal_state(). Prázdny = fail-open.
      route: výstup query_router; gate koná LEN pri "temporal".
      return_dropped: ak True, vráť (kept, dropped) namiesto len kept.

    Returns:
      kept  (list) alebo (kept, dropped) ak return_dropped.
    """
    # NO-OP mimo temporal route — flat recall ostáva nedotknutý
    if route != "temporal":
        return (list(candidates), []) if return_dropped else list(candidates)

    # FAIL-OPEN: bez temporal dôkazu nefiltrujeme
    if not temporal_state:
        return (list(candidates), []) if return_dropped else list(candidates)

    kept, dropped = [], []
    for c in candidates:
        cid = c.get("id")
        st = temporal_state.get(cid)
        # id bez záznamu = aktívny (nič o ňom nevieme → nechaj prejsť)
        if st is None:
            kept.append(c)
            continue
        if st.get("valid_until") is not None:
            # superseded — potlač, ale zapíš dôvod (nič ticho nezahadzujeme)
            d = dict(c)
            d["_dropped_reason"] = "superseded"
            d["valid_until"] = st.get("valid_until")
            d["superseded_by"] = st.get("superseded_by")
            dropped.append(d)
        else:
            kept.append(c)

    return (kept, dropped) if return_dropped else kept


if __name__ == "__main__":
    import sys
    import json
    obj = json.loads(sys.stdin.read())
    kept = when_gate(obj.get("candidates", []),
                     obj.get("temporal_state", {}),
                     route=obj.get("route", "point"))
    print(json.dumps({"kept": kept, "n": len(kept)}, ensure_ascii=False, indent=2))
