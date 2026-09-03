#!/usr/bin/env python3
"""mem_usage_audit.py — Zarába pamäť na seba? (spike 012, jeden príkaz)

Odpovedá na: koľko recallov, z akých zdrojov (človek vs stroj), a či injektované
uzly reálne existujú v indexe (probe/duchovia vylúčené). Nahrádza ručné hashovacie
hry z auditu 2026-09-01.

Beží pod /usr/bin/python3 (stdlib only, offline). Číta state/events.jsonl +
state/mem_index.jsonl. Nič nemodifikuje — čisto read-only.

Použitie:
    /usr/bin/python3 toolkit/mem_usage_audit.py            # celé okno
    /usr/bin/python3 toolkit/mem_usage_audit.py --days 7   # len posledných 7 dní
"""
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(ROOT, "state", "events.jsonl")
INDEX = os.path.join(ROOT, "state", "mem_index.jsonl")

# zdroje, ktoré znamenajú "stroj sa pýta sám seba"
MACHINE = {"session_hook", "initiative", "patterns", "eval"}
# zdroje, ktoré znamenajú REÁLNE interaktívne použitie (človek sa pýta)
HUMAN = {"interactive", "whatsapp", "cli"}
# 'adhoc' = NEZNÁME: buď eventy spred spike 012 (source sa nelogoval), alebo
# neotagovaný volajúci. NIE je dôkaz človeka ani stroja — vlastná kategória.


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def main(argv):
    days = None
    if "--days" in argv:
        try:
            days = int(argv[argv.index("--days") + 1])
        except Exception:
            days = None

    events = _load_jsonl(EVENTS)
    index_ids = {r.get("id") for r in _load_jsonl(INDEX) if r.get("id") is not None}

    recalls = [e for e in events if e.get("event") == "recall_hits"]
    if days is not None:
        # ts je ISO string; lexikografické porovnanie stačí na oddelenie dní
        import datetime
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        recalls = [e for e in recalls if (e.get("ts") or "") >= cutoff]

    if not recalls:
        print("Žiadne recall_hits eventy v okne — pamäť sa nevolala vôbec.")
        return 0

    ts_all = sorted(e.get("ts", "") for e in recalls if e.get("ts"))
    span = f"{ts_all[0][:10]} → {ts_all[-1][:10]}" if ts_all else "?"

    by_source = Counter()
    ghost_by_source = Counter()   # recall vrátil len id-á čo NIE sú v indexe (probe/duch)
    real_by_source = Counter()    # recall vrátil aspoň jedno reálne id
    ids_seen = defaultdict(Counter)

    # spike 012 / fix B: query_hash dedukcia. Staré netagované eventy (source=adhoc/None)
    # majú často ROVNAKÝ query_hash ako neskoršie OTAGOVANÉ strojové volania (initiative,
    # session_hook bežia fixné dotazy). Odvoď ich source z tej zhody, nech 'neznáme' kôš
    # neprefukuje falošne — čisté deterministické priradenie, žiadny model. Odvodené
    # zdroje sa značia hviezdičkou (napr. 'initiative*') a rátajú sa ako STROJ.
    qh_known = defaultdict(Counter)
    for e in recalls:
        d = e.get("data", {})
        s = d.get("source")
        if s and s != "adhoc":
            qh_known[d.get("query_hash")][s] += 1
    qh_to_src = {qh: c.most_common(1)[0][0] for qh, c in qh_known.items()}

    for e in recalls:
        data = e.get("data", {})
        src = data.get("source") or "adhoc"
        ids0 = data.get("ids", []) or []
        if src == "adhoc":
            inferred = qh_to_src.get(data.get("query_hash"))
            if inferred:
                src = inferred + "*"   # odvodené z query_hash = ten istý stroj
            elif ids0 and not any(i in index_ids for i in ids0):
                src = "probe(ghost)"   # fixné id mimo indexu = test probe
        by_source[src] += 1
        ids = data.get("ids", []) or []
        real = [i for i in ids if i in index_ids]
        for i in ids:
            ids_seen[src][i] += 1
        if ids and not real:
            ghost_by_source[src] += 1
        elif real:
            real_by_source[src] += 1

    total = sum(by_source.values())

    def _base(s):
        return s[:-1] if s.endswith("*") else s   # 'initiative*' -> 'initiative'

    machine = sum(v for s, v in by_source.items() if _base(s) in MACHINE)
    human = sum(v for s, v in by_source.items() if _base(s) in HUMAN)
    probe = sum(v for s, v in by_source.items() if s.startswith("probe"))
    unknown = total - machine - human - probe  # len naozaj nezaraditeľné
    ghost = sum(ghost_by_source.values())

    print("=" * 60)
    print("  PAMÄŤ — AUDIT POUŽÍVANIA (spike 012)")
    print("=" * 60)
    print(f"okno:            {span}" + (f"  (posledných {days} dní)" if days else ""))
    print(f"recall_hits:     {total}")
    print(f"  stroj:         {machine}  ({100*machine//total if total else 0}%)  [session_hook/initiative/patterns/eval; * = odvodené z query_hash]")
    print(f"  človek:        {human}  ({100*human//total if total else 0}%)  [interactive/whatsapp/cli]")
    print(f"  probe/test:    {probe}  ({100*probe//total if total else 0}%)  [fixné id mimo indexu = smoke/test]")
    print(f"  neznáme:       {unknown}  ({100*unknown//total if total else 0}%)  [netagované A query_hash nikde inde = jediní kandidáti na skrytého človeka]")
    print(f"  z toho duch:   {ghost}  (recall vrátil len id-á mimo indexu)")
    print()
    print("podľa zdroja:")
    for src, n in by_source.most_common():
        b = _base(src)
        if src.startswith("probe"):
            tag = "PROBE/TEST"
        elif b in MACHINE:
            tag = "STROJ" + ("*" if src.endswith("*") else "")
        elif b in HUMAN:
            tag = "ČLOVEK"
        else:
            tag = "neznáme (adhoc)"
        g = ghost_by_source.get(src, 0)
        gtxt = f", {g} duch" if g else ""
        uniq = len(ids_seen[src])
        print(f"  {src:14s} {n:4d}×   {tag:18s}  ({uniq} unik. id{gtxt})")
    print()

    # VERDIKT — čestný: adhoc NIE je dôkaz používania, je to neznáme.
    print("verdikt:")
    if human >= 10:
        print(f"  ✓ {human} potvrdených interaktívnych (človek) recallov — pamäť sa reálne číta.")
    elif human + unknown >= 10:
        print(f"  ~ {human} potvrdených + {unknown} možných ľudských — hraničné, sleduj trend.")
    else:
        cap = human + unknown
        print(f"  ~ {machine} strojových recallov; ľudských najviac {cap} (potvrdené {human})")
        print("    za celé okno — pamäť je čisto pasívny bootstrap. Interaktívne")
        print("    použitie NEPOTVRDENÉ (spike012 potvrdený tretíkrát).")
    if unknown:
        print(f"  pozn.: {unknown} netagovaných s unikátnym query_hash = jediní možní")
        print("    skrytí ľudia (horná hranica). Zvyšok 'adhoc' priradený stroju/probe cez query_hash.")
        print("    Po napojení source (spike 012) majú nové recally niesť konkrétny zdroj;")
        print("    ak adhoc neubúda, ostal neotagovaný volajúci — dohľadaj ho.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
