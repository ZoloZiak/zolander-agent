#!/usr/bin/env python3
"""ascend.py — F8 abstraction engine. Rebrik ako OPERACIA, nie sklad.

Konsolidacia = STUPANIE k pociatku manifoldu (r->0). Kym sen (F4) robil len
L0->L1, ascend robi CELY rebrik ako opakovatelnu operaciu "vystup o priecku":
  L0 epizoda  -> L1 destilat   (co sa naozaj stalo, bez omacky)
  L1 destilat -> L2 princip    ("coho je toto instancia?")
  L2 princip  -> L3 meta-ramec (svetonazor/vzorec myslenia, najblizsie k r->0)

Kazdy krok:
  1. nacita koncepty zdrojovej vrstvy z mem_index.jsonl
  2. (volitelne) zhlukne podobne cez NATIVNU Lorentzovu vzdialenost (YAR v5 129D),
     aby destilat nemiesal jablka/hrusky
  3. LLM (opus default, gpt-mini lacno) odpovie na "coho je toto instancia?" -> vyssi koncept
  4. ulozi novy koncept do vyssej vrstvy cez zol_mem.py remember (natívny 129D
     Lorentz, mensi polomer r = blizsie k jadru), s links na zdrojove id

READ-ONLY voci nizsim vrstvam: NIC nemaze, len PRIDAVA vyssi koncept (hodnoty-
ako-kod P2 — destrukcia az po audite veducka). Idempotencia rieseneho: uz-
povysene koncepty su oznacene v state/ascended.json (nestupaju 2x zbytocne).

EMBEDDING: natívny YAR v5 (embed_yar.py) cez .venv-yar (torch+transformers==5.0.0),
NIE starý cosine embed.py. Volá sa subprocessom (JSONL in/out), takže ascend.py
sam nepotrebuje torch. Clustering = Lorentzova vzdialenost (mensie=blizsie).

Beh:
  $VPY ascend.py step --from L1 --to L2                 # jeden priecok
  $VPY ascend.py step --from L1 --to L2 --model gpt-mini --dry
  $VPY ascend.py ladder                                 # cely rebrik L0->L1->L2->L3
"""
import os
import sys
import json
import math
import time
import argparse
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
IDX = os.path.join(STATE, "mem_index.jsonl")
ASCENDED = os.path.join(STATE, "ascended.json")
ZOL_MEM = os.path.join(ROOT, "toolkit", "zol_mem.py")
# natívny YAR v5 embedder + jeho dedikovany venv (torch+transformers==5.0.0)
VENV_YAR = os.path.join(ROOT, ".venv-yar", "bin", "python")
EMBED = os.path.join(ROOT, "toolkit", "embed_yar.py")
ASCLOG = os.path.join(LOGS, "ascend.log")
# clustering prah v Lorentzovej vzdialenosti (arccosh): mensie=blizsie.
# empiricky ~1.0 = rozumny prah "ta ista tema" pre YAR v5 129D.
LDIST_THRESHOLD = float(os.environ.get("ASCEND_LDIST", "1.0"))

# palantir_client (chat/LLM pre distill) zije v zolo2.0/toolkit; embedding ide
# ODDELENE subprocessom do VENV_YAR (torch tam, nie tu).
sys.path.insert(0, os.path.join(HOME, "zolo2.0", "toolkit"))

# rebrik: z coho na co, a aky kind ma vysledok
STEPS = {("L0", "L1"): "semantic", ("L1", "L2"): "semantic", ("L2", "L3"): "identity"}
# ako sa pyta LLM podla cielovej vrstvy
ASCEND_Q = {
    "L1": ("Zhrn tieto epizody do 1-2 viet TRVALEHO poznatku (co sa naozaj naucilo/"
           "stalo). Fakt alebo vzorec, ziadny datum, ziadna omacka."),
    "L2": ("Coho su tieto poznatky INSTANCIOU? Pomenuj 1 vseobecnejsi PRINCIP, ktory "
           "ich zastresuje. Jedna hutna veta, o uroven abstraktnejsie."),
    "L3": ("Aky META-RAMEC / vzorec myslenia stoji nad tymito principmi? Pomenuj "
           "svetonazorovu zasadu na najvyssej urovni. Jedna veta, blizko koreňa."),
}


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(ASCLOG, "a") as f:
        f.write(f"{now()} | {msg}\n")


def load_index():
    if not os.path.exists(IDX):
        return []
    rows = []
    for line in open(IDX):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_ascended():
    if os.path.exists(ASCENDED):
        try:
            return set(json.load(open(ASCENDED)))
        except Exception:
            return set()
    return set()


def save_ascended(s):
    json.dump(sorted(s), open(ASCENDED, "w"))


def embed_many(texts):
    payload = "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n"
                      for i, t in enumerate(texts))
    p = subprocess.run([VENV_YAR, EMBED], input=payload, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("embed_yar zlyhal: " + p.stderr[-400:])
    by = {}
    for line in p.stdout.splitlines():
        line = line.strip()
        if line and line.startswith("{"):
            o = json.loads(line)
            by[o["id"]] = o["vector"]
    return [by[i] for i in range(len(texts))]


def ldist(a, b):
    """Lorentzova vzdialenost dvoch 129D bodov (arccosh(-<a,b>_L)). Mensie=blizsie."""
    mink = -a[0] * b[0] + sum(x * y for x, y in zip(a[1:], b[1:]))
    val = -mink
    if val < 1.0:
        val = 1.0
    return math.acosh(val)


def cluster(rows, threshold=LDIST_THRESHOLD):
    """Greedy zhlukovanie podla LORENTZOVEJ vzdialenosti (mensie=blizsie, prah je
    HORNA hranica). Ked <3 polozky, jedna skupina (netreba embed).
    FALLBACK: ak by zhlukovanie vyrobilo SAME singletony (nic sa neabstrahuje),
    vrat vsetko ako JEDNU skupinu — den/vrstva sa ma vzdy zhrnut aspon raz."""
    if len(rows) < 3:
        return [rows] if rows else []
    vecs = embed_many([r.get("text", "") for r in rows])
    groups = []            # list of [rows]
    reps = []
    for r, v in zip(rows, vecs):
        placed = False
        for gi, rep in enumerate(reps):
            if ldist(v, rep) <= threshold:
                groups[gi].append(r)
                placed = True
                break
        if not placed:
            reps.append(v)
            groups.append([r])
    if all(len(g) < 2 for g in groups):
        return [rows]
    return groups


def distill(group, to_layer, model):
    from palantir_client import chat
    joined = "\n".join(f"- {r.get('text', '')}" for r in group)
    system = ("Si Zolander — dekonstrukcny nastroj na luciditu. Stupas po rebriku "
              "abstrakcie k jadru (r->0). Ziadna lichotka, ziadna omacka, po slovensky.")
    q = ASCEND_Q[to_layer]
    prompt = f"{q}\n\nZdroj:\n{joined}\n\nVysledok (alebo NIC ak niet co abstrahovat):"
    txt = chat(prompt, model=model, max_tokens=220, system=system).strip()
    if not txt or txt.upper().startswith("NIC"):
        return None
    return txt


def remember(text, to_layer, kind, links):
    payload = json.dumps({"text": text, "kind": kind, "layer": to_layer,
                          "salience": 0.8, "confidence": 0.75,
                          "source": "ascend", "project": "zolander",
                          "links": links}, ensure_ascii=False)
    p = subprocess.run([VENV_YAR, ZOL_MEM, "remember"], input=payload,
                       capture_output=True, text=True)
    if p.returncode != 0:
        log(f"remember {to_layer} zlyhal: {p.stderr[-300:]}")
        return None
    try:
        return json.loads(p.stdout.strip()).get("remembered")
    except Exception:
        return None


def step(from_layer, to_layer, model="opus", dry=False):
    if (from_layer, to_layer) not in STEPS:
        raise ValueError(f"neplatny priecok {from_layer}->{to_layer}; povolene: {list(STEPS)}")
    kind = STEPS[(from_layer, to_layer)]
    rows = load_index()
    done = load_ascended()
    src = [r for r in rows if r.get("layer") == from_layer and r["id"] not in done]
    if len(src) < 2:
        log(f"step {from_layer}->{to_layer}: len {len(src)} zdrojov (<2), preskakujem")
        return {"from": from_layer, "to": to_layer, "created": [], "note": "malo zdrojov"}
    groups = cluster(src)
    created = []
    for g in groups:
        if len(g) < 2:
            continue  # jedina polozka netvori princip
        text = distill(g, to_layer, model)
        ids = [r["id"] for r in g]
        if not text:
            continue
        if dry:
            created.append({"text": text, "from_ids": ids, "dry": True})
            continue
        nid = remember(text, to_layer, kind, ",".join(str(i) for i in ids))
        if nid:
            for i in ids:
                done.add(i)
            created.append({"id": nid, "layer": to_layer, "text": text, "from_ids": ids})
    if not dry:
        save_ascended(done)
    log(f"step {from_layer}->{to_layer} ({model}): vytvorene={len(created)} groups={len(groups)}")
    return {"from": from_layer, "to": to_layer, "created": created}


def ladder(model="opus", dry=False):
    out = []
    for fr, to in (("L0", "L1"), ("L1", "L2"), ("L2", "L3")):
        out.append(step(fr, to, model=model, dry=dry))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    ps = sub.add_parser("step")
    ps.add_argument("--from", dest="frm", required=True)
    ps.add_argument("--to", dest="to", required=True)
    ps.add_argument("--model", default="opus")
    ps.add_argument("--dry", action="store_true")
    pl = sub.add_parser("ladder")
    pl.add_argument("--model", default="opus")
    pl.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if args.cmd == "step":
        print(json.dumps(step(args.frm, args.to, model=args.model, dry=args.dry),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "ladder":
        print(json.dumps(ladder(model=args.model, dry=args.dry),
                         ensure_ascii=False, indent=2))
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
