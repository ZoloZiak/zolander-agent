#!/usr/bin/env python3
"""MELD parser regresný test: odseknutý JSON od Gemini (token limit) nesmie vrátiť None.

Bug 2026-08-31: Gemini vracal `{"verdict":"MERGE` (bez uzatváracej }), rigidný regex
to čítal ako None -> falošné "split", zamaskovaný 3-way konsenzus na 2/3 majoritu.

Offline, žiadny LLM. Spusti: /usr/bin/python3 toolkit/test_meld_parse_truncated.py
"""
import os
import sys

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLKIT)

import meld_moa as mm  # noqa: E402


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    print("=== MELD parser: odseknutý JSON + edge cases ===")
    cases = [
        ('{"verdict":"MERGE","reason":"ten isty fakt"}', "MERGE"),   # plný JSON
        ('{"verdict":"MERGE', "MERGE"),                               # odseknuté (Gemini bug)
        ('{"verdict":"MER', None),                                    # odseknuté v slove -> None (nedá sa istiť)
        ('nejaka preambula {"verdict":"RELATE","reason":"x"}', "RELATE"),
        ('{"verdict":"CONFLICT"', "CONFLICT"),
        ('__ERR__ timeout', None),
        ('', None),
    ]
    for txt, want in cases:
        got, _ = mm._parse(txt)
        if got != want:
            fail(f"vstup {txt!r}: dostal {got!r}, čakal {want!r}")
        print(f"  OK  {txt[:40]!r:44s} -> {got}")
    print("VYSLEDOK: MELD parser znáša odseknutý JSON OK")


if __name__ == "__main__":
    main()
