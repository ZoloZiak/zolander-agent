#!/usr/bin/env python3
"""test_query_router.py — ŽL4 lexikálny query router (kolo30, 2608 ŽL cesta).

Router je deterministický (LLM-free) klasifikátor typu dotazu — rozhodne, KTORÁ
recall stratégia sa má zapojiť:
  point     — bežný konkrétny lookup (default, flat recall)
  aggregate — "zhrň všetko o X" → ŽL3 subtree expansion
  relation  — "ako súvisí X s Y" → graph traversal
  temporal  — "kedy/aktuálne/posledný" → ŽL5 when-gate prefilter

Iron law (TDD): tento test bol napísaný PRED query_router() a musel zlyhať
(ImportError), kým funkcia neexistovala.

Beh: /usr/bin/python3 toolkit/test_query_router.py   (offline, bez modelu/DB)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from query_router import query_router, ROUTE_POINT, ROUTE_AGGREGATE, ROUTE_RELATION, ROUTE_TEMPORAL

FAILS = []


def check(query, expected_route, note=""):
    r = query_router(query)
    got = r["route"]
    if got != expected_route:
        FAILS.append(f"  '{query[:50]}' → čakal {expected_route}, dostal {got} (dôvod: {r.get('reason')}) {note}")


# --- AGGREGATE: "zhrň všetko o X" typy ---
check("zhrň všetko o Wole", ROUTE_AGGREGATE)
check("daj mi prehľad všetkého o __PROJECT__", ROUTE_AGGREGATE)
check("summarize everything about the memory pipeline", ROUTE_AGGREGATE)
check("čo všetko vieš o mojom zdraví", ROUTE_AGGREGATE)
check("kompletný obraz o statínoch", ROUTE_AGGREGATE)

# --- RELATION: "ako súvisí X s Y" typy ---
check("ako súvisí MELD s IBIA", ROUTE_RELATION)
check("aký je vzťah medzi Z1 a Lorentz priestorom", ROUTE_RELATION)
check("čo spája pitavastatín a myopatiu", ROUTE_RELATION)
check("how is the router connected to the recall flow", ROUTE_RELATION)

# --- TEMPORAL: "kedy/aktuálne/posledný" typy ---
check("kedy sme robili MELD writeback", ROUTE_TEMPORAL)
check("aká je aktuálna adresa vedúcka", ROUTE_TEMPORAL)
check("kde teraz bývam", ROUTE_TEMPORAL)
check("posledný stav claim ledgera", ROUTE_TEMPORAL)
check("what is the current model", ROUTE_TEMPORAL)

# --- POINT: bežné konkrétne dotazy (default, NESMIE spadnúť do inej vetvy) ---
check("PESEL vedúcka", ROUTE_POINT)
check("aké lieky znáša", ROUTE_POINT)
check("meno prenajímateľa", ROUTE_POINT)
check("fingerprint identity", ROUTE_POINT)

# --- ROBUSTNOSŤ: prázdny / degenerovaný vstup ---
r = query_router("")
if r["route"] != ROUTE_POINT:
    FAILS.append(f"  prázdny vstup má default POINT, dostal {r['route']}")
r = query_router(None)
if r["route"] != ROUTE_POINT:
    FAILS.append(f"  None vstup má default POINT, dostal {r['route']}")

# --- PRIORITA: relation pred aggregate (obe kľúčové slová naraz) ---
# "ako súvisí všetko o X s Y" — relation signál je špecifickejší
r = query_router("ako súvisí všetko o MELD s pamäťou")
if r["route"] not in (ROUTE_RELATION, ROUTE_AGGREGATE):
    FAILS.append(f"  zmiešaný dotaz má byť relation/aggregate, nie {r['route']}")

# --- KONTRAKT: router vždy vráti route + reason + confidence ---
r = query_router("zhrň všetko o X")
for key in ("route", "reason", "confidence"):
    if key not in r:
        FAILS.append(f"  kontrakt: chýba kľúč '{key}' vo výstupe routera")

if FAILS:
    print("FAIL query_router:")
    for f in FAILS:
        print(f)
    sys.exit(1)
print("PASS query_router: aggregate/relation/temporal/point klasifikácia + robustnosť + kontrakt")
