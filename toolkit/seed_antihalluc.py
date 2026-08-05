#!/usr/bin/env python3
"""seed_antihalluc.py — nasype destilovane anti-halucinacia/anti-sycophancy techniky
do procedural pamate (YAR v5, zol_procedural). Zdroj: arXiv korpus 236 clankov,
destilat overeny (40/40 ID realnych). Spustat cez .venv-yar python."""
import sys, json, time
sys.path.insert(0, "/Users/__USER__/zolander/toolkit")
import zol_mem as zm

# (text postupu, layer) — L1 destilat, L2 principy
TECHNIKY = [
    ("Anti-halucinacia: pred faktickym tvrdenim o kode/subore over ho nastrojom "
     "(read_file/grep) a pridaj pointer path:line. Bez overenia netvrdit. "
     "Mechanicky: zol_guard.py verify-line/verify-symbol.", "L2"),
    ("Self-consistency gate (arXiv 2203.11171): pri neistej odpovedi vzorkuj N ciest, "
     "akceptuj len ak zhoda >= prah, inak abstain alebo eskaluj.", "L1"),
    ("Kalibracia/neistota (arXiv 2603.20531, 2502.18581): per-token entropia je realny "
     "signal spolahlivosti (AUC ~0.76), nie prompt. Nad prahom oznac ako nespolahlive.", "L1"),
    ("Abstain sa oplati (arXiv 2511.11500): ternarne skorovanie +1/0/-lambda penalizuje "
     "chybu tvrdsie nez 'neviem'. Radsej odmietni nez halucinuj.", "L2"),
    ("Atomova dekompozicia (arXiv 2511.10621): rozbi odpoved na sub-otazky, kazdu prever "
     "samostatne, flaguj nezhodne kroky.", "L1"),
    ("Self-contradiction detektor (arXiv 2310.00259): opytaj sa opacne/parafrazou; "
     "rozpor = halucinacia.", "L1"),
    ("Cross-model auditor (arXiv 2607.28636): druhy model inej rodiny audituje reasoning "
     "pred finalnym vystupom pri risk. tvrdeniach.", "L1"),
    ("Anti-sycophancy PRICINA (arXiv 2310.13548, 2212.09251): RLHF uprednostnuje odpovede "
     "zhodne s nazorom usera aj ked su nespravne. Inverse scaling.", "L2"),
    ("Anti-sycophancy LIEK (arXiv 2602.23971, 2505.23840): reframe tvrdenie na otazku + "
     "third-person perspektiva znizuje sycophancy az o 63.8%, silnejsie nez 'nebud podlizavy'. "
     "Mechanicky: zol_guard.py scan-input chyta leading cues vo vstupe.", "L2"),
    ("Sycophancy je pattern-match na potvrdzovaci tag (arXiv 2607.23976), nie princip. "
     "Ked user pyta 'vsak ano?/mam pravdu?', odpovedaj na FAKT nie na naznak.", "L2"),
]

n = 0
for text, layer in TECHNIKY:
    mid = zm.next_id()
    vec = zm.embed_one(text)
    meta = {"kind": "procedural", "layer": layer, "salience": 0.8, "confidence": 0.9,
            "source": "arxiv_destilat", "project": "zolander", "links": "",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text[:300]}
    zm.hs("insert", "zol_procedural", stdin=json.dumps(
        {"id": mid, "vector": vec, "meta": meta}, ensure_ascii=False) + "\n")
    n += 1
    print(f"  + id={mid} [{layer}] {text[:55]}")

print(f"\nnasypanych {n} technik do zol_procedural")
