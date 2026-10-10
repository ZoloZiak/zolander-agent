#!/usr/bin/env python3
"""zol_digest_cron.py — prebuduje stupňovaný digest pre VŠETKY archivované miestnosti.

Prejde ~/projects/zolander/state/matrix_archive/*.meta.json, pre každú miestnosť
dosyncuje archív a prepočíta digest (len zmenené pásma — cache šetrí LLM volania).
Volá sa z cronu mimo hot-path hooku, aby dlhá pamäť ostala čerstvá.
"""
import os
import sys
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from zol_matrix_archive import sync_room  # noqa: E402
from zol_matrix_digest import build_digest  # noqa: E402

ARCHIVE_DIR = os.path.expanduser("~/projects/zolander/state/matrix_archive")


def main():
    metas = glob.glob(os.path.join(ARCHIVE_DIR, "*.meta.json"))
    if not metas:
        print("žiadne archivované miestnosti")
        return
    total_calls = 0
    for m in metas:
        try:
            meta = json.load(open(m, encoding="utf-8"))
        except Exception:
            continue
        room = meta.get("room_id")
        if not room:
            continue
        try:
            added = sync_room(room)
            r = build_digest(room)
            calls = int(r.get("llm_calls", 0) or 0)
            total_calls += calls
            print(f"{room[:40]}: +{added} nových, {calls} LLM volaní")
        except Exception as exc:
            print(f"{room[:40]}: CHYBA {exc}")
    print(f"spolu {total_calls} LLM volaní")


if __name__ == "__main__":
    main()
