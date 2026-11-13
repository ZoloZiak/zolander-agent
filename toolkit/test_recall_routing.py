#!/usr/bin/env python3
"""test_recall_routing.py — integrácia query_router → when_gate/subtree do recall.

Testuje seam `zol_mem._apply_query_route(cand, query, obj, ...)`, ktorý zapája
ŽL4 router + ŽL5 when-gate + ŽL3 subtree do recall pipeline. Injektovateľné
deps (temporal_state, index, subtree_fn) → čistý offline test bez DB/LLM.

Zásada (rovnaká ako StateMem/graph_expand): router beží vždy (lacný, informatívny),
akcie sú AKTÍVNE default (router/when_gate/subtree neboli dokázané škodlivé —
na rozdiel od graph_expand), ale s kill-switchom obj['route_disable']=True.
"""
import os
import sys
import types
import importlib.util

# Stub heavy/local deps → offline unit test (rovnaký vzor ako test_recall_current_state).
_ey = types.ModuleType("embed_yar")
setattr(_ey, "embed_one", lambda text: [0.0] * 129)
sys.modules["embed_yar"] = _ey
_zp = types.ModuleType("zol_paths")
setattr(_zp, "NODE", "node")
setattr(_zp, "HS", "hs.mjs")
setattr(_zp, "NODE_ENV", {})
setattr(_zp, "ZROOT", "/tmp")
sys.modules["zol_paths"] = _zp

TK = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TK)
spec = importlib.util.spec_from_file_location("zol_mem", os.path.join(TK, "zol_mem.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("neviem načítať zol_mem.py")
zol_mem = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zol_mem)


def _cand(cid, score, text=""):
    return {"id": cid, "score": score, "meta": {"text": text, "kind": "semantic"}}


def test_temporal_route_drops_superseded():
    """Temporálny dotaz → when_gate potlačí superseded kandidát."""
    cand = [_cand(1, 0.9, "stará adresa"), _cand(2, 0.8, "nová adresa")]
    tstate = {1: {"valid_until": "2026-01-01T00:00:00", "superseded_by": 2}}
    out, info = zol_mem._apply_query_route(
        cand, "aká je moja AKTUÁLNA adresa teraz", {},
        temporal_state=tstate, index={}, subtree_fn=lambda *a, **k: [])
    ids = [c["id"] for c in out]
    assert info["route"] == "temporal", f"čakal temporal, dostal {info['route']}"
    assert 1 not in ids, "superseded #1 mal byť potlačený pri temporal dotaze"
    assert 2 in ids, "aktuálny #2 musí prejsť"


def test_point_route_is_noop():
    """Bežný point dotaz → kandidáti nedotknutí (žiadny drop, žiadna expanzia)."""
    cand = [_cand(1, 0.9, "fakt A"), _cand(2, 0.8, "fakt B")]
    tstate = {1: {"valid_until": "2026-01-01T00:00:00", "superseded_by": 2}}
    out, info = zol_mem._apply_query_route(
        cand, "kde mám uložený config", {},
        temporal_state=tstate, index={}, subtree_fn=lambda *a, **k: [])
    ids = [c["id"] for c in out]
    assert info["route"] == "point", f"čakal point, dostal {info['route']}"
    # point NEROBÍ hard-drop superseded (to je práca StateMem filtra pred týmto)
    assert ids == [1, 2], f"point mal nechať poradie nedotknuté, dostal {ids}"


def test_aggregate_route_expands_subtree():
    """Agregačný dotaz → subtree expansion dotiahne parent kandidáta."""
    cand = [_cand(10, 0.9, "seed o téme X")]
    index = {20: {"text": "rodičovský kontext X", "kind": "semantic"}}
    # subtree_fn(mid) → parent hrany: uzol 10 má rodiča 20
    subtree_fn = lambda mid, *a, **k: [{"child": 10, "parent": 20, "depth": 1}] if mid == 10 else []
    out, info = zol_mem._apply_query_route(
        cand, "zhrň všetko o téme X", {},
        temporal_state={}, index=index, subtree_fn=subtree_fn)
    ids = [c["id"] for c in out]
    assert info["route"] == "aggregate", f"čakal aggregate, dostal {info['route']}"
    assert 20 in ids, f"subtree parent #20 mal pribudnúť, dostal {ids}"
    added = [c for c in out if c.get("subtree_expanded")]
    assert added and added[0]["seed_id"] == 10, "pridaný uzol musí niesť seed_id audit"


def test_kill_switch_disables_actions():
    """route_disable=True → router pobeží (info), ale žiadna akcia sa neaplikuje."""
    cand = [_cand(1, 0.9, "stará"), _cand(2, 0.8, "nová")]
    tstate = {1: {"valid_until": "2026-01-01T00:00:00", "superseded_by": 2}}
    out, info = zol_mem._apply_query_route(
        cand, "aká je AKTUÁLNA adresa teraz", {"route_disable": True},
        temporal_state=tstate, index={}, subtree_fn=lambda *a, **k: [])
    ids = [c["id"] for c in out]
    assert info["route"] == "temporal", "router má klasifikovať aj pri disable"
    assert info.get("applied") is False, "pri kill-switchi sa akcia NESMIE aplikovať"
    assert ids == [1, 2], f"kill-switch mal nechať kandidátov tak, dostal {ids}"


def test_failopen_on_broken_deps():
    """Rozbité deps (subtree_fn hodí výnimku) → recall nespadne, vráti seedy."""
    cand = [_cand(10, 0.9, "seed")]

    def boom(*a, **k):
        raise RuntimeError("graf nedostupný")

    out, info = zol_mem._apply_query_route(
        cand, "zhrň všetko o X", {}, temporal_state={},
        index={20: {"text": "x"}}, subtree_fn=boom)
    ids = [c["id"] for c in out]
    assert 10 in ids, "fail-open: seed musí prežiť aj pri rozbitom subtree_fn"


def test_aggregate_dedup_when_parent_already_in_pool():
    """Ak je parent UŽ v poole (bežné na malom korpuse), expansion ho NEZDUPLIKUJE.

    Reálne zistenie (E2E na živej DB, 405 záznamov, fetch≈80): parenty seedov sú
    takmer vždy už vytiahnuté flat recallom → added=0. Nie je to bug, je to dedup.
    Tento test to zamkne, aby sa 'added=0' nemýlilo s 'expansion sa nespustil'.
    """
    cand = [_cand(10, 0.9, "seed"), _cand(20, 0.7, "parent už v poole")]
    index = {20: {"text": "rodič", "kind": "semantic"}}
    subtree_fn = lambda mid, *a, **k: [{"child": 10, "parent": 20, "depth": 1}] if mid == 10 else []
    out, info = zol_mem._apply_query_route(
        cand, "zhrň všetko o X", {},
        temporal_state={}, index=index, subtree_fn=subtree_fn)
    ids = [c["id"] for c in out]
    assert info["route"] == "aggregate"
    assert info["applied"] is True, "expansion sa MAL spustiť (aj keď nič nepridá)"
    assert ids.count(20) == 1, f"parent #20 nesmie byť zduplikovaný, dostal {ids}"
    assert info.get("added") == 0, "keď parent už v poole, added=0 (dedup, nie chyba)"


if __name__ == "__main__":
    test_temporal_route_drops_superseded()
    test_point_route_is_noop()
    test_aggregate_route_expands_subtree()
    test_aggregate_dedup_when_parent_already_in_pool()
    test_kill_switch_disables_actions()
    test_failopen_on_broken_deps()
    print("PASS recall routing: temporal-drop/point-noop/aggregate-expand/dedup/kill-switch/fail-open")
