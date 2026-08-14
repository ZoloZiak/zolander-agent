#!/usr/bin/env python3
"""mem_support.py — support-check pamate (Self-RAG grounding, arXiv:2310.11511).

Problem: recall vrati kandidatov, ale agent ich berie ako pravdu. Support-check =
pred POUZITIM spomienky over, ci REALNE podporuje tvrdenie ktore ide agent povedat.
To robi pamat UZEMNENOU (Royse "grounding": asociacia bez kotvy je bezcenna), nie doverivou.

Vstup: claim (co ide agent tvrdit) + kandidati (spomienky z recallu).
Vystup per kandidat: verdikt SUPPORTS | CONTRADICTS | UNRELATED + kratke zdovodnenie.
Deterministicky rozhoduje OPUS (reasoning, nie embed). Fail-open: chyba -> "UNKNOWN"
(nezablokuje, len oznaci ze sa nedalo overit).

CLI:  echo '{"claim":"...","candidates":[{"id":1,"text":"..."}]}' | mem_support.py
alebo importovatelne: from mem_support import support_check
Bezi pod .venv-yar (palantir_client). Model prepisatelny ZOL_SUPPORT_MODEL (default opus).
"""
import os
import re
import sys
import json

sys.path.insert(0, "/Users/__USER__/zolo2.0/toolkit")
MODEL = os.environ.get("ZOL_SUPPORT_MODEL", "opus")

_SYS = (
    "Si prisny overovac uzemnenia (grounding). Dostanes TVRDENIE a zoznam SPOMIENOK. "
    "Pre kazdu spomienku rozhodni, ci REALNE podporuje tvrdenie:\n"
    "  SUPPORTS   = spomienka priamo potvrdzuje tvrdenie\n"
    "  CONTRADICTS= spomienka tvrdeniu odporuje\n"
    "  UNRELATED  = spomienka s tvrdenim nesuvisi / nestaci na potvrdenie\n"
    "Bud prisny: ciastocna tematicka podobnost NIE je SUPPORTS. Vrat IBA JSON pole "
    "[{\"id\":<cislo>,\"verdict\":\"SUPPORTS|CONTRADICTS|UNRELATED\",\"why\":\"<max 12 slov>\"}]."
)


def support_check(claim, candidates, model=MODEL):
    """candidates: list dict s 'id','text'. Vrat list verdiktov. Fail-open -> UNKNOWN."""
    if not candidates:
        return []
    try:
        from palantir_client import chat
    except Exception:
        return [{"id": c["id"], "verdict": "UNKNOWN", "why": "checker nedostupny"} for c in candidates]
    lines = [f"TVRDENIE: {claim}", "", "SPOMIENKY:"]
    for c in candidates:
        lines.append(f"- id={c['id']}: {(c.get('text') or '')[:300]}")
    try:
        out = chat("\n".join(lines), model=model, max_tokens=800, system=_SYS)
    except Exception:
        out = None
    if not out:
        return [{"id": c["id"], "verdict": "UNKNOWN", "why": "LLM zlyhal"} for c in candidates]
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return [{"id": c["id"], "verdict": "UNKNOWN", "why": "parse zlyhal"} for c in candidates]
    try:
        verds = json.loads(m.group(0))
    except Exception:
        return [{"id": c["id"], "verdict": "UNKNOWN", "why": "json zlyhal"} for c in candidates]
    by_id = {v.get("id"): v for v in verds if isinstance(v, dict)}
    # dopln chybajuce ako UNKNOWN (aby vystup pokryl vsetkych kandidatov)
    out_list = []
    for c in candidates:
        v = by_id.get(c["id"], {"id": c["id"], "verdict": "UNKNOWN", "why": "chyba vo vystupe"})
        out_list.append(v)
    return out_list


def main():
    obj = json.loads(sys.stdin.read())
    res = support_check(obj["claim"], obj.get("candidates", []))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
