#!/usr/bin/env python3
"""Offline test hybrid fuzie (BM25 min-max score fusion) — bez DB/YAR.
Overuje ze pri jednoznacnom lexikalnom signale vyhra spravny zaznam a ze sumove
zaznamy nepredbehnu silny lexikalny hit (regresia RRF ktora tu zlyhala).
Spustenie: /usr/bin/python3 toolkit/test_mem_lexical.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mem_lexical as ml


DOCS = [
    {"id": 383, "text": "IZBY (pokoj) na prenajom = samostatny projekt zolander-rooms",
     "kind": "semantic", "layer": "L1", "ts": ""},
    {"id": 52, "text": "Pouzivatel __USER__ ma OrbStack a kontajner hyperspace na porte 50051",
     "kind": "semantic", "layer": "L0", "ts": ""},
    {"id": 140, "text": "__USER__ trva na tom aby bola praca urobena poriadne",
     "kind": "identity", "layer": "L0", "ts": ""},
    {"id": 303, "text": "Telekom vracia nespotrebovany kredit na pisomnu ziadost",
     "kind": "semantic", "layer": "L0", "ts": ""},
]


class TestBM25(unittest.TestCase):
    def test_diacritics_fold(self):
        # 'Izby' aj 'izbami' sa foldnu+stemnu na spolocny zaklad
        self.assertEqual(ml._stem(ml._fold("Izby")), ml._stem(ml._fold("izbami")))

    def test_morphology_cases(self):
        # KLUCOVE: pady/cislo jedneho slova zdielaju kmen (izba/izby/izbu/izbe/izbami)
        stems = {ml._stem(ml._fold(w)) for w in ["izba", "izby", "izbu", "izbe", "izbami"]}
        self.assertEqual(len(stems), 1, f"pady sa nespojili: {stems}")
        # pokoj mnozne aj jednotne
        self.assertEqual(ml._stem(ml._fold("pokoje")), ml._stem(ml._fold("pokoj")))

    def test_no_overstem(self):
        # kratke/nezhodne slova sa nezosekaju na blbost (kmen >=3)
        self.assertEqual(ml._stem("dom"), "dom")
        self.assertTrue(len(ml._stem(ml._fold("watcher"))) >= 3)

    def test_query_singular_matches_plural(self):
        # 'izbu' (jedn.) query najde dokument s 'IZBY' (mnozne) — regresia co padala
        res = ml.bm25("hladam izbu", DOCS)
        self.assertTrue(res)
        self.assertEqual(res[0][0], 383)

    def test_rooms_query_wins(self):
        res = ml.bm25("izby pokoj prenajom", DOCS)
        self.assertTrue(res, "BM25 nevratilo nic")
        self.assertEqual(res[0][0], 383)

    def test_strong_gap(self):
        # jednoznacny hit ma mat vyrazne vyssie skore nez zvysok
        res = ml.bm25("izby pokoj prenajom zolander-rooms", DOCS)
        top = res[0][1]
        second = res[1][1] if len(res) > 1 else 0.0
        self.assertGreater(top, second * 1.8)

    def test_no_match_empty(self):
        # query bez zhody nevrati sum (BM25 vracia len docs so skore>0)
        self.assertEqual(ml.bm25("kryptomena bitcoin ethereum", DOCS), [])

    def test_orbstack_query(self):
        res = ml.bm25("orbstack kontajner hyperspace port", DOCS)
        self.assertEqual(res[0][0], 52)


class TestScoreFusion(unittest.TestCase):
    """Replika min-max score fusion z zol_mem.cmd_recall (izolovane, bez YAR/DB)."""
    def _fuse(self, sem_pairs, lex_pairs, w_sem=1.0, w_lex=1.3):
        def norm(pairs):
            if not pairs:
                return {}
            vals = [s for _, s in pairs]
            lo, hi = min(vals), max(vals)
            if hi <= lo:
                return {i: 1.0 for i, _ in pairs}
            return {i: (s - lo) / (hi - lo) for i, s in pairs}
        sn, ln = norm(sem_pairs), norm(lex_pairs)
        ids = set(sn) | set(ln)
        return sorted(ids, key=lambda i: -(w_sem*sn.get(i, 0)+w_lex*ln.get(i, 0)))

    def test_strong_lexical_beats_weak_consensus(self):
        # sem: sumove zaznamy stredne (regresia RRF); lex: 383 jasne prve
        sem = [(313, 1/(1+1.04)), (52, 1/(1+0.97)), (140, 1/(1+0.93))]
        lex = [(383, 17.5), (241, 6.0), (313, 5.2), (52, 4.8)]
        order = self._fuse(sem, lex)
        self.assertEqual(order[0], 383)

    def test_semantic_only_still_works(self):
        # ked lex nic nevrati, poradie urcuje semantika
        sem = [(10, 1/(1+0.2)), (11, 1/(1+0.5)), (12, 1/(1+0.9))]
        order = self._fuse(sem, [])
        self.assertEqual(order[0], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
