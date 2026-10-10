#!/usr/bin/env python3
"""zol_book.py — MOST z Zolanderovej pamate do zolo2.0 knihy (kolekcia lorentz129).

Preco MOST a nie kopia: 6110 atomov knihy je LITERARNY material (4-vrstvovy narativ,
fikcia). NEpatri do zol_mem ako Zolanderova identita —
skreslilo by to jeho usudok na starte kazdej session. Namiesto toho Zolander do knihy
NAHLIADNE len ked VEDOME pracuje na zolo2.0: zavola tento most, dostane relevantne atomy.

Ziadna kopia dat, ziadne zahltenie zol_mem. Cisto read-only pohlad do UZ existujucej
HyperspaceDB kolekcie lorentz129 (6110 vekt., YAR 129D Lorentz).

POZOR (overene): YAR je slaby na diferenciaciu (distances ~0.91-0.94 tesne) — ranking
funguje, ale ber vysledok ako "tematicky pribuzne", nie presny match. Text sa dohladava
z ingest_meta.jsonl podla gid (DB meta text nedrzi; getPoints haluci NOT_FOUND).

Pouzitie:
  echo '{"query":"hlavna tema knihy","topk":8}' | python3 zol_book.py
  python3 zol_book.py "moc, stat, kontrola"            # skratka, topk=8
Volitelne v JSON: "theme":"D" (filter temy), "layer":"L4" (filter vrstvy), "topk":N.

Bezi pod /usr/bin/python3 (stdlib). Embed cez zolander venv-yar (subprocess),
search cez zolo2.0 hs.mjs (node). Vsetko fail-safe, ziadny zapis.
"""
import os, sys, json, math, subprocess

HOME = os.path.expanduser("~")
ZOLANDER = os.path.join(HOME, "projects", "zolander")
ZOLO = os.path.join(HOME, "projects", "zolo2.0")
VENV_YAR = os.path.join(ZOLANDER, ".venv-yar", "bin", "python")
EMBED_YAR = os.path.join(ZOLANDER, "toolkit", "embed_yar.py")
HS_MJS = os.path.join(ZOLO, "toolkit", "hs.mjs")
INGEST = os.path.join(ZOLO, "work", "ingest_meta.jsonl")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, node_modules
NODE_PATH = node_modules()
COLLECTION = "lorentz129"


def embed_query(text):
    """YAR 129D Lorentz vektor + hyperboloid reprojekcia (server chce presne <x,x>=-1)."""
    payload = json.dumps({"id": 0, "text": text}, ensure_ascii=False) + "\n"
    r = subprocess.run([VENV_YAR, EMBED_YAR], input=payload,
                       capture_output=True, text=True, timeout=120)
    line = ""
    for ln in r.stdout.strip().splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            line = ln
    if not line:
        raise RuntimeError("embed zlyhal: " + r.stderr.strip()[-200:])
    vec = json.loads(line)["vector"]
    if len(vec) != 129:
        raise RuntimeError("embed vratil dim %d, cakane 129" % len(vec))
    x0 = math.sqrt(1.0 + sum(z * z for z in vec[1:]))  # reprojekcia float64
    return [x0] + vec[1:]


def search(vec, topk):
    q = json.dumps({"vector": vec})
    env = dict(os.environ, NODE_PATH=NODE_PATH)
    r = subprocess.run([NODE, HS_MJS, "search", COLLECTION, str(topk)],
                       input=q, capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        raise RuntimeError("hs.mjs search zlyhal: " + r.stderr.strip()[-200:])
    return json.loads(r.stdout.strip())


def load_texts(gids):
    """Dohladaj clean/orig text pre dane gid z ingest_meta (jednorazovy scan)."""
    want = set(str(g) for g in gids)
    out = {}
    if not os.path.exists(INGEST):
        return out
    for ln in open(INGEST, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        g = str(o.get("gid"))
        if g in want:
            out[g] = {"clean": o.get("clean", ""), "orig": o.get("orig", ""),
                      "category": o.get("category", ""), "insight": o.get("insight", "")}
            if len(out) == len(want):
                break
    return out


def bridge(query, topk=8, theme=None, layer=None):
    # nadmerne natiahni ak filtrujeme, potom orezeme
    raw_k = topk * 4 if (theme or layer) else topk
    vec = embed_query(query)
    hits = search(vec, raw_k)
    if theme:
        hits = [h for h in hits if h.get("meta", {}).get("theme") == theme]
    if layer:
        hits = [h for h in hits if h.get("meta", {}).get("layer") == layer]
    hits = hits[:topk]
    texts = load_texts([h.get("id") for h in hits])
    res = []
    for h in hits:
        g = str(h.get("id"))
        t = texts.get(g, {})
        res.append({
            "gid": g,
            "distance": round(h.get("distance", 0), 4),
            "theme": h.get("meta", {}).get("theme", ""),
            "layer": h.get("meta", {}).get("layer", ""),
            "category": h.get("meta", {}).get("category", ""),
            "text": t.get("clean") or t.get("orig", ""),
            "insight": t.get("insight", ""),
        })
    return res


def main():
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    else:
        raw = ""
    if raw.startswith("{"):
        obj = json.loads(raw)
    elif len(sys.argv) > 1:
        obj = {"query": " ".join(sys.argv[1:])}
    elif raw:
        obj = {"query": raw}
    else:
        print("pouzitie: echo '{\"query\":\"...\",\"topk\":8}' | zol_book.py", file=sys.stderr)
        sys.exit(2)
    res = bridge(obj["query"], int(obj.get("topk", 8)),
                 obj.get("theme"), obj.get("layer"))
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
