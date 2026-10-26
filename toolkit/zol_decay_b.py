#!/usr/bin/env python3
"""zol_decay_b.py — B-strana decay salience (UpdatePayload RPC).

Kedže server metadata je updatable (update_payload), decay na B strane:
  1. scroll všetky body kolekcie zol_mem,
  2. nová salience = stará * 0.95 (rovnaké ako A decay v drame),
  3. update_payload s CELOU metadannou mapou (server nahrádza celú mapu —
     preto posielame všetky kľúče, len salience úbytok).

SDK update_payload má bug (vráti resp.code, ale proto má StatusResponse
{status}) — tento klient ida rovno cez stub a overí reťazec statusu.
Nič nemaže; zlyhania hlasí poctivo. Vystup JSON, exit 0 = ok.

Pouzitie: python toolkit/zol_decay_b.py [--factor 0.95] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLKIT)
sys.path.insert(0, TOOLKIT)

COLLECTION = "zol_mem"

import zol_mem_text  # noqa: E402

CLIENT = zol_mem_text.make_client()
RPC = zol_mem_text.rpc_call


def update_metadata_raw(point_id, metadata, collection):
    """SDK update_payload má bug (vracia resp.code, ale v(proto) StatusResponse
    má 'status'). Rovnaká RPC cesta cez stub, overená na reťazec statusu."""
    import hyperspace_pb2
    req = hyperspace_pb2.UpdatePayloadRequest(id=point_id, metadata=dict(metadata),
                                              collection=collection)
    resp = CLIENT.stub.UpdatePayload(req, metadata=CLIENT.metadata)
    ok = "updated" in str(resp.status or "").lower()
    return ok, None if ok else f"status: {resp.status!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", type=float, default=0.95)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pts, err = RPC(CLIENT.scroll, limit=4000, collection=COLLECTION)
    if err:
        print(json.dumps({"ok": False, "error": f"RPC chyba pri scrolli: {err}"}, ensure_ascii=False))
        return 1

    changed, errors, unchanged = [], [], 0
    for p in (pts or []):
        md = p.get("metadata") or {}
        try:
            old = float(md.get("salience", 0.4))
        except (TypeError, ValueError):
            unchanged += 1
            continue
        new = round(old * args.factor, 4)
        if abs(new - old) < 1e-9:
            unchanged += 1
            continue
        if args.dry_run:
            changed.append({"id": p.get("id"), "old": old, "new": new, "dry_run": True})
            continue
        new_md = dict(md)
        new_md["salience"] = f"{new:.4f}"
        ok, uerr = update_metadata_raw(p.get("id"), new_md, COLLECTION)
        if uerr or not ok:
            errors.append({"id": p.get("id"), "err": (uerr or "ok=false")[:150]})
        else:
            changed.append({"id": p.get("id"), "old": old, "new": new})

    print(json.dumps({"ok": not errors, "mode": "decay-b", "factor": args.factor,
                      "changed": changed, "unchanged": unchanged, "errors": errors},
                     ensure_ascii=False, indent=1))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
