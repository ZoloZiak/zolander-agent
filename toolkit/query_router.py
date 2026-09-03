#!/usr/bin/env python3
"""query_router.py — ŽL4 lexikálny query router (kolo30, ŽL cesta zo scout backlogu).

Deterministický (LLM-free) klasifikátor TYPU dotazu. Rozhoduje, KTORÁ recall
stratégia sa má zapojiť — bez modelu, bez DB, čisto lexikálne markery:

  point     — bežný konkrétny lookup (DEFAULT, flat hybrid recall)
  aggregate — "zhrň všetko o X"      → ŽL3 subtree expansion (BFS parent/child)
  relation  — "ako súvisí X s Y"     → graph traversal medzi kotvami
  temporal  — "kedy / aktuálne / X"  → ŽL5 when-gate (supersedes/valid_until prefilter)

Prečo deterministický a nie LLM: router beží na KAŽDOM recall-e (aj v daemon
slučke bez MCP/LLM). Musí byť lacný, offline a re-spustiteľný. Vzor prevzatý z
lens.should_double_take() — markery + skóre, konzervatívny default.

Priorita pri zhode viacerých signálov (od najšpecifickejšieho):
  relation > aggregate > temporal > point
Dôvod: "ako súvisí" je najužší signál (dva subjekty + spojka); "všetko o"
je široký zber; temporal je modifikátor; point je fallback keď nič nesedí.

Router NEROBÍ samotný retrieval — len oznámi rozhodnutie. Zapojenie do
cmd_recall() je OPT-IN (route_enable), aby produkčný recall ostal flat, kým
graph-recall eval neukáže čísla (rovnaká disciplína ako graph_expand).
"""

ROUTE_POINT = "point"
ROUTE_AGGREGATE = "aggregate"
ROUTE_RELATION = "relation"
ROUTE_TEMPORAL = "temporal"

# --- AGGREGATE: široký zber "všetko/prehľad/kompletný obraz o X" ---
_AGG_MARKERS = [
    "všetko o", "vsetko o", "všetkého o", "vsetkeho o", "čo všetko", "co vsetko",
    "prehľad", "prehlad", "kompletný obraz", "kompletny obraz", "zhrň", "zhrn",
    "zhrnutie", "summarize everything", "everything about", "overview of",
    "celkový pohľad", "celkovy pohlad", "všetky", "complete picture",
]

# --- RELATION: dva subjekty + spojka vzťahu ---
_REL_MARKERS = [
    "ako súvisí", "ako suvisi", "aký je vzťah", "aky je vztah", "vzťah medzi",
    "vztah medzi", "čo spája", "co spaja", "spojitosť medzi", "spojitost medzi",
    "how is", "related to", "relationship between", "connection between",
    "connected to", "súvislosť", "suvislost", "prepojenie medzi",
]
# relation vyžaduje aj indikátor DVOCH subjektov (spojka), inak je to falošná zhoda
_REL_JOINERS = [" s ", " so ", " medzi ", " a ", " with ", " to ", " between ", " and "]

# --- TEMPORAL: časový/aktuálnostný modifikátor ---
_TEMP_MARKERS = [
    "kedy ", "aktuál", "aktual", "teraz", "posledn", "current", "latest",
    "momentál", "momental", "práve teraz", "prave teraz", "najnovš", "najnovs",
    "dnes", "v súčasnosti", "v sucasnosti", "still ", "as of",
]


def _norm(text):
    return (text or "").strip().lower()


def _hits(text, markers):
    return [m for m in markers if m in text]


def query_router(query):
    """Klasifikuj typ dotazu. Vráť {route, reason, confidence, signals}.

    confidence: hrubý ukazovateľ sily signálu (počet zhôd), 0.0 pre čistý default.
    Deterministické, idempotentné, žiadny vedľajší efekt.
    """
    t = _norm(query)
    if not t:
        return {"route": ROUTE_POINT, "reason": "prázdny vstup — default point",
                "confidence": 0.0, "signals": {}}

    agg = _hits(t, _AGG_MARKERS)
    rel = _hits(t, _REL_MARKERS)
    temp = _hits(t, _TEMP_MARKERS)
    # relation platí len ak je aj spojka dvoch subjektov
    rel_valid = rel and any(j in t for j in _REL_JOINERS)

    signals = {"aggregate": agg, "relation": rel, "temporal": temp,
               "relation_valid": bool(rel_valid)}

    # priorita: relation > aggregate > temporal > point
    if rel_valid:
        return {"route": ROUTE_RELATION,
                "reason": f"vzťahový marker {rel!r} + spojka dvoch subjektov",
                "confidence": min(1.0, 0.5 + 0.25 * len(rel)), "signals": signals}
    if agg:
        return {"route": ROUTE_AGGREGATE,
                "reason": f"agregačný marker {agg!r} (zhrň všetko o X)",
                "confidence": min(1.0, 0.5 + 0.25 * len(agg)), "signals": signals}
    if temp:
        return {"route": ROUTE_TEMPORAL,
                "reason": f"temporálny marker {temp!r} (kedy/aktuálne/posledný)",
                "confidence": min(1.0, 0.5 + 0.25 * len(temp)), "signals": signals}
    return {"route": ROUTE_POINT, "reason": "žiadny špeciálny marker — flat point recall",
            "confidence": 0.0, "signals": signals}


if __name__ == "__main__":
    import sys
    import json
    q = sys.stdin.read() if not sys.stdin.isatty() else " ".join(sys.argv[1:])
    try:
        obj = json.loads(q)
        q = obj.get("query", "")
    except Exception:
        pass
    print(json.dumps(query_router(q), ensure_ascii=False, indent=2))
