#!/usr/bin/env python3
"""edge_selfaudit.py — MOZOG SEBAOBJAVU parent-hran. Zolander si SAM najde INVERTED/
SAME_LAYER parent hrany a rozhodne, co s nimi, PRESNE tak ako to robil clovek rucne
(dva nezavisle signaly: layer schema + r_opus geometria). LEN CITA, nic nemeni.

PRECO EXISTUJE (root-cause pointa): find_roof.py mal geometricku poistku uz davno, ale
bol RUCNY nastroj bokom slucky — Zolander ho v spanku nevolal, takze apex #490 a inverzie
nasiel az clovek. Tento skript je ta ista logika, ale ZAPOJENA do slucky: dava strojovy
verdikt, ktory si initiative/dream vyzdvihne a navrhne cez "Navrh #N".

METODA (nenavodna, pravidlo VOPRED — aby sme nefitovali zaver):
  Pre kazdu podozrivu parent hranu DIETA->RODIC mame dva NEZAVISLE signaly:
    (S1) LAYER: ordinal vrstvy L0<L1<L2<L3 (rodic ma byt VYSSIE).
    (S2) GEOMETRIA: r_opus / layer_score (radialna abstraktnost; VYSSIE r = abstraktnejsie).
  Rozhodnutie (konzervativne, default related):
    - REVERSE  : OBA signaly zhodne hovoria "dieta je abstraktnejsie nez rodic"
                 (layer dieta > rodic A r_dieta - r_rodic >= GEOM_MARGIN). Hrana je naopak.
    - KEEP     : OBA signaly zhodne hovoria "rodic je abstraktnejsi" (layer rodic > dieta
                 A r_rodic - r_dieta >= GEOM_MARGIN). INVERTED flag bol len artefakt hrubej
                 vrstvy — geometria potvrdzuje validnu is-a. Nechaj parent.
    - RELATED  : signaly nesuhlasia, alebo su tesne (|delta r| < GEOM_MARGIN), alebo
                 same-layer. Meta-principy nie su hierarchia — su surodenci.
  FAIL-OPEN: chyba r_opus u niektoreho uzla -> ten par sa oznaci need_geom a NEROBI sa
  z neho tvrdy verdikt (nenavrhne sa zmena z nedostatku dat).

APEX (organicky nadhlad, to co Plan B hladal umelo): najabstraktnejsi uzol (max r_opus)
v komponente hubov — reportuje sa ako kandidat na strechu, ale NEVYNUCUJE sa.

Vystup: state/edge_selfaudit.json (strojovy) + citatelny sumar na stdout.
Bezi pod /usr/bin/python3 (stdlib, ZIADNY model). Idempotentne, read-only.
"""
import os
import sys
import json
from collections import Counter, defaultdict

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
OUT = os.path.join(STATE, "edge_selfaudit.json")
LORD = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
# minimalny rozdiel r_opus aby sme signal povazovali za smerodajny (nie sum).
# odvodene z rucnej F3b analyzy: tesne pary |delta|<=0.03 = siblings; margin 0.05 = bezpecny.
GEOM_MARGIN = float(os.environ.get("ZOL_SELFAUDIT_GEOM_MARGIN", "0.05"))


def _read_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def load_rows():
    return {r["id"]: r for r in _read_jsonl(IDX) if "id" in r}


def _layer_ord(r):
    return LORD.get(r.get("layer")) if r else None


def _rscore(r):
    """r_opus abstraktnost = layer_score (zapecene). None ak nezapecene."""
    if not r:
        return None
    v = r.get("layer_score")
    return float(v) if isinstance(v, (int, float)) else None


def short(rows, mid):
    r = rows.get(mid)
    if not r:
        return f"[#{mid} NEEXISTUJE]"
    t = (r.get("text") or "")[:55]
    rs = _rscore(r)
    return f"#{mid}({r.get('layer','?')},r={rs if rs is not None else '?'}): {t}"


def classify_pair(child, parent, rows):
    """Vrat (verdict, detail) pre parent hranu child->parent (parent ma byt abstraktnejsi)."""
    rc, rp = rows.get(child), rows.get(parent)
    if not rc or not rp:
        return "orphan", {"reason": "uzol neexistuje"}
    lc, lp = _layer_ord(rc), _layer_ord(rp)
    sc, sp = _rscore(rc), _rscore(rp)
    d = {"child_layer": rc.get("layer"), "parent_layer": rp.get("layer"),
         "r_child": sc, "r_parent": sp}
    if sc is None or sp is None:
        d["reason"] = "chyba r_opus (need_geom)"
        return "need_geom", d
    dr = round(sc - sp, 4)  # >0 => dieta abstraktnejsie nez rodic
    d["delta_r_child_minus_parent"] = dr
    # signal S1 (layer): +1 rodic vyssie, -1 dieta vyssie, 0 rovnake/nezname
    if lc is None or lp is None:
        s1 = 0
    elif lp > lc:
        s1 = 1
    elif lp < lc:
        s1 = -1
    else:
        s1 = 0
    # signal S2 (geometria): +1 rodic abstraktnejsi, -1 dieta abstraktnejsie, 0 tesne
    if dr <= -GEOM_MARGIN:
        s2 = 1     # r_parent vyssie => rodic abstraktnejsi
    elif dr >= GEOM_MARGIN:
        s2 = -1    # r_child vyssie => dieta abstraktnejsie
    else:
        s2 = 0
    d["s1_layer"], d["s2_geom"] = s1, s2
    # rozhodnutie: OBA signaly musia zhodne ukazovat rovnaky smer
    if s1 == 1 and s2 == 1:
        d["reason"] = "oba signaly: rodic abstraktnejsi = validna is-a (flag bol artefakt vrstvy)"
        return "keep", d
    if s1 == -1 and s2 == -1:
        d["reason"] = "oba signaly: dieta abstraktnejsie = hrana je naopak"
        return "reverse", d
    # PRIAMY KONFLIKT (layer a geometria si PROTIRECIA, oba nenulove): lacne signaly
    # nestacia -> eskaluj na 3-lab LLM (presne to co clovek robil rucne pri #478->#685).
    # NEROZHODUJ z dvoch sporiacich sa lacnych signalov (nefituj zaver).
    if s1 * s2 == -1:
        d["reason"] = ("KONFLIKT layer vs geometria -> potrebny 3-lab arbiter "
                       "(lacne signaly na meta-principy nestacia)")
        return "need_llm", d
    # inak: aspon jeden signal je nulovy (tesna geometria alebo rovnaka vrstva) =
    # genuinne lateralne -> surodenci. Meta-principy nie su hierarchia.
    d["reason"] = "aspon jeden signal nulovy (tesne/same-layer) -> surodenci"
    return "related", d


def audit(write=True):
    """Spusti sebaaudit, vrat result dict. write=True zapise state/edge_selfaudit.json.
    Importovatelne sluckou (dream/initiative) — bez printu, bez exitu."""
    rows = load_rows()
    edges = _read_jsonl(EDGES)
    par, seen = [], set()
    for e in edges:
        if e.get("edge") != "parent":
            continue
        f, t = e.get("from"), e.get("to")
        if f == t or (f, t) in seen:
            continue
        seen.add((f, t))
        par.append((f, t))

    # audit kategorie (kompatibilne s edge_audit.py) + sebaobjav verdikty na podozrivych
    cats = defaultdict(list)
    proposals = []           # tvrde navrhy zmeny (reverse/related) s dovodom
    keep_confirmed = []      # INVERTED flag ktory geometria vyvratila (nechat parent)
    need_geom = []
    need_llm = []            # priamy konflikt layer vs geometria -> arbiter 3-lab
    for (f, t) in par:
        rc, rp = rows.get(f), rows.get(t)
        if not rc or not rp:
            cats["ORPHAN"].append((f, t))
            continue
        lc, lp = _layer_ord(rc), _layer_ord(rp)
        # audit label podla samotnej vrstvy (ako edge_audit)
        if lp is not None and lc is not None and lp > lc:
            cats["OK"].append((f, t))
            continue  # cista is-a podla vrstvy — nepreveruj
        elif lp is not None and lc is not None and lp == lc:
            cats["SAME_LAYER"].append((f, t))
        else:
            cats["INVERTED"].append((f, t))
        # podozriva hrana -> sebaobjav rozhodnutie cez dva signaly
        verdict, detail = classify_pair(f, t, rows)
        rec = {"child": f, "parent": t, "verdict": verdict,
               "child_txt": (rc.get("text") or "")[:70],
               "parent_txt": (rp.get("text") or "")[:70], **detail}
        if verdict in ("reverse", "related"):
            proposals.append(rec)
        elif verdict == "keep":
            keep_confirmed.append(rec)
        elif verdict == "need_geom":
            need_geom.append(rec)
        elif verdict == "need_llm":
            need_llm.append(rec)

    # APEX kandidat: najabstraktnejsi uzol (max r_opus) medzi tymi co maju deti (su rodicia)
    parents_with_kids = {t for (_, t) in par}
    apex = None
    best = -1.0
    for pid in parents_with_kids:
        rs = _rscore(rows.get(pid))
        if rs is not None and rs > best:
            best, apex = rs, pid
    apex_rec = None
    if apex is not None:
        apex_rec = {"id": apex, "r_opus": best,
                    "text": (rows[apex].get("text") or "")[:90],
                    "layer": rows[apex].get("layer")}

    result = {
        "parent_distinct": len(par),
        "counts": {k: len(v) for k, v in cats.items()},
        "suspicious_total": len(cats["INVERTED"]) + len(cats["SAME_LAYER"]),
        "verdicts": Counter(p["verdict"] for p in proposals),
        "proposals": proposals,            # reverse/related — navrhy na zmenu
        "keep_confirmed": keep_confirmed,  # INVERTED flag vyvrateny geometriou
        "need_geom": need_geom,            # chyba r_opus, treba re-bake
        "need_llm": need_llm,              # konflikt layer vs geom -> 3-lab arbiter
        "apex_candidate": apex_rec,
        "geom_margin": GEOM_MARGIN,
    }
    # Counter nie je JSON-serializovatelny priamo pre "verdicts" nested? je dict subclass -> ok
    result["verdicts"] = dict(result["verdicts"])
    if write:
        json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    result["_rows"] = rows  # pomocne pre print (nezapisuje sa do JSON)
    return result


def main():
    result = audit(write=True)
    rows = result.pop("_rows", {})
    cats_counts = result["counts"]
    proposals = result["proposals"]
    keep_confirmed = result["keep_confirmed"]
    need_llm = result["need_llm"]
    need_geom = result["need_geom"]
    apex_rec = result["apex_candidate"]
    n_rev = sum(1 for p in proposals if p["verdict"] == "reverse")
    n_rel = sum(1 for p in proposals if p["verdict"] == "related")
    print("=" * 70)
    print("SEBAAUDIT parent-hran (dva nezavisle signaly: layer + r_opus)")
    print(f"  distinct parent hran: {result['parent_distinct']}")
    print(f"  OK (is-a podla vrstvy):   {cats_counts.get('OK', 0)}")
    print(f"  INVERTED:                 {cats_counts.get('INVERTED', 0)}")
    print(f"  SAME_LAYER:               {cats_counts.get('SAME_LAYER', 0)}")
    print(f"  ORPHAN:                   {cats_counts.get('ORPHAN', 0)}")
    print("-" * 70)
    print(f"  NAVRH reverse (otoc):     {n_rev}")
    print(f"  NAVRH related (surodenci):{n_rel}")
    print(f"  KEEP (geom vyvratil flag):{len(keep_confirmed)}")
    print(f"  need_llm (konflikt->3lab): {len(need_llm)}")
    print(f"  need_geom (chyba r_opus): {len(need_geom)}")
    if apex_rec:
        print(f"  APEX kandidat: #{apex_rec['id']} (r={apex_rec['r_opus']}) {apex_rec['text'][:60]}")
    print("=" * 70)
    for p in proposals[:10]:
        arrow = "OTOCIT" if p["verdict"] == "reverse" else "->related"
        print(f"  [{arrow}] {short(rows, p['child'])}  -->  {short(rows, p['parent'])}")
    print(f"\nZapisane: {OUT}")
    # exit kod: 0 = cisto (ziadne navrhy), 2 = su navrhy na opravu (signal pre slucku)
    return 2 if proposals else 0


if __name__ == "__main__":
    sys.exit(main())
