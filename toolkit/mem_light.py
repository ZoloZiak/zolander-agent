#!/usr/bin/env python3
"""mem_light.py — light pamat pre Zolander opencode port (Faza 1).

Nahrada za zol_mem.py (HyperspaceDB + YAR/Lorentz) KED backend nie je
k dispozicii: append-only JSONL + lexikalny recall (keyword prekryv + recencia).
Ziadne embeddings, ziadna server databaza — len stdlib. Honesty: toto NIE je
hyperbolicka pamat, je to L0 papiervinkovy zapisok s indexom. Faza 2 to
migroruje do lorentz zol_mem, ked budu vektor + server dostupne.

Pouzitie:
  python toolkit/mem_light.py remember --text "..." [--kind episodic] [--layer L0] [--confidence 0.6] [--source manual] [--project ""]
  python toolkit/mem_light.py recall --query "..." [--topk 5]
  python toolkit/mem_light.py list [--topk 10]
  python toolkit/mem_light.py decay          # (rezerva; ordering nie je podstatny v L0)

Vystup JSON na stdout. Exit 0 = ok.
Skladanie: state/ (git-ignored), cesta derivuje z ZOLANDER_ROOT/HOME.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata

KINDS = {"episodic", "semantic", "procedural", "identity"}
LAYERS = {"L0", "L1", "L2", "L3"}
STOP = {
    "a", "na", "v", "je", "sa", "som", "si", "o", "z", "do", "pre", "ako", "to",
    "the", "is", "and", "or", "in", "on", "of", "to", "for", "with", "at", "by",
}


def memory_path() -> str:
    root = os.environ.get("ZOLANDER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "state", "zol_memory.jsonl")


def ensure_file(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        open(path, "a", encoding="utf-8").close()


def load_all(path: str) -> list[dict]:
    out: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in "".join(c if c.isalnum() or c.isspace() else " " for c in text).split() if t and t not in STOP]


def cmd_remember(args: argparse.Namespace) -> dict:
    if args.kind not in KINDS:
        raise SystemExit(f"kind musi byt jedna z {sorted(KINDS)} (vyuziva zol_mem schema, faz 2 migracia)")
    if args.layer not in LAYERS:
        raise SystemExit(f"layer musi byt jedna z {sorted(LAYERS)}")
    conf = float(args.confidence)
    if not 0.0 <= conf <= 1.0:
        raise SystemExit("confidence musi byt 0..1")
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "text": args.text.strip(),
        "kind": args.kind,
        "layer": args.layer,
        "salience": round(conf * 0.8, 3),  # light: salience ~ confidence; faz-2 decay ju prepise
        "confidence": conf,
        "source": args.source,
        "project": args.project,
        "engine": "light-lexical-v1",
    }
    # A2A podpis (nepovinny): ak orchestr (napr. zol_remember_dual.py) dodal
    # podpis, nesiem ho v zazname; verify ho moze prepoctat.
    if getattr(args, "sig", None):
        entry["sig"] = args.sig
        entry["sig_from_fp"] = args.from_fp
        entry["sig_ts"] = args.ts_signed
    if not entry["text"]:
        raise SystemExit("text nesmie byt prazdny")
    path = memory_path()
    ensure_file(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"ok": True, "mode": "remember", "id": entry["ts"], "entry": entry}


def cmd_recall(args: argparse.Namespace) -> dict:
    path = memory_path()
    if not os.path.exists(path):
        return {"ok": True, "mode": "recall", "engine": "light-lexical-v1", "hits": [], "empty": True, "note": "bez pamati (prva session?) — recall prazdny, nepredstieraj kontext"}
    items = load_all(path)
    if not items:
        return {"ok": True, "mode": "recall", "engine": "light-lexical-v1", "hits": [], "empty": True}
    qtokens = set(normalize(args.query)) if args.query else set()
    scored: list[tuple[float, int, dict]] = []
    for i, m in enumerate(items):
        base = float(m.get("salience", 0.3)) + 0.2 * float(m.get("confidence", 0.5))
        recency = i / max(len(items), 1)  # novsie vyssie
        if qtokens:
            mtokens = set(normalize(str(m.get("text", ""))))
            overlap = len(mtokens & qtokens)
            if overlap == 0:
                continue
            score = overlap * 2.0 + base + recency * 0.5
        else:
            score = base + recency
        scored.append((score, i, m))
    scored.sort(key=lambda t: t[0], reverse=True)
    hits = [{"score": round(s, 3), **m} for s, _, m in scored[: args.topk]]
    return {"ok": True, "mode": "recall", "engine": "light-lexical-v1", "hits": hits, "empty": False}


def cmd_list(args: argparse.Namespace) -> dict:
    path = memory_path()
    items = load_all(path) if os.path.exists(path) else []
    hits = []
    for m in items[-args.topk :]:
        nm = dict(m)
        nm.setdefault("score", None)
        hits.append(nm)
    return {"ok": True, "mode": "list", "hits": list(reversed(hits)), "count": len(items)}


def cmd_decay(_: argparse.Namespace) -> dict:
    return {"ok": True, "mode": "decay", "note": "light-faza1: decay nesupinazal; faz-2 port zolander_dream.py to nadobudne"}


def main() -> None:
    p = argparse.ArgumentParser(description="Zolander light pamat (faza 1, bez LLM/backendu)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("remember")
    r.add_argument("--text", required=True)
    r.add_argument("--kind", default="episodic")
    r.add_argument("--layer", default="L0")
    r.add_argument("--confidence", default="0.6")
    r.add_argument("--source", default="manual")
    r.add_argument("--project", default="")
    r.add_argument("--sig", default=None, help="A2A Ed25519 hex podpis (nepovinny)")
    r.add_argument("--from_fp", dest="from_fp", default=None)
    r.add_argument("--ts_signed", default=None)
    r.set_defaults(func=cmd_remember)
    q = sub.add_parser("recall")
    q.add_argument("--query", default="")
    q.add_argument("--topk", type=int, default=5)
    q.set_defaults(func=cmd_recall)
    l = sub.add_parser("list")
    l.add_argument("--topk", type=int, default=10)
    l.set_defaults(func=cmd_list)
    d = sub.add_parser("decay")
    d.set_defaults(func=cmd_decay)
    args = p.parse_args()
    print(json.dumps(args.func(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
