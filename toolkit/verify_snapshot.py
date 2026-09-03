#!/usr/bin/env python3
"""verify_snapshot.py — staticky (sebestacny) snapshot verify.jsonl do HTML.

Na rozdiel od verify_dashboard.py (zivy server, len localhost) toto vyrobi JEDEN
HTML subor s udalostami zapecenymi dnu -> da sa poslat cez WhatsApp / otvorit
kdekolvek bez servera. Nie je zivy (zmrazeny stav), regeneruj pre aktualny.

Spustenie: /usr/bin/python3 ~/projects/zolander/toolkit/verify_snapshot.py
Vystup: ~/projects/zolander/state/reports/verify_snapshot.html
"""
import os
import json
import time
import html

LOG = os.path.expanduser("~/projects/zolander/logs/verify.jsonl")
OUT = os.path.expanduser("~/projects/zolander/state/reports/verify_snapshot.html")

COLOR = {
    "fired": "#3b82f6", "moa_start": "#8b5cf6", "moa_file": "#06b6d4",
    "moa_pass": "#16a34a", "moa_block": "#f87171", "mechanical_block": "#f87171",
    "moa_error": "#eab308", "moa_disabled": "#9ca3af", "moa_skip": "#9ca3af",
}

rows = []
try:
    with open(LOG, encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if l:
                try:
                    rows.append(json.loads(l))
                except Exception:
                    pass
except FileNotFoundError:
    pass

counts = {"block": 0, "pass": 0, "error": 0}
for r in rows:
    ev = r.get("ev", "")
    if ev in ("moa_block", "mechanical_block"):
        counts["block"] += 1
    elif ev == "moa_pass":
        counts["pass"] += 1
    elif ev == "moa_error":
        counts["error"] += 1

# posledných 300 pre kompaktnosť
show = rows[-300:]
items = []
for r in show:
    ev = r.get("ev", "?")
    col = COLOR.get(ev, "#4b5563")
    extra = ""
    for k, v in r.items():
        if k in ("ts", "ev"):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        extra += f' <span style="color:#94a3b8">{html.escape(str(k))}=</span>{html.escape(str(v))}'
    items.append(
        f'<div style="padding:5px 10px;margin:4px 0;border-radius:6px;'
        f'border-left:3px solid {col};background:#12151d;white-space:pre-wrap;word-break:break-word">'
        f'<span style="color:#6b7280;margin-right:8px">{html.escape(r.get("ts",""))}</span>'
        f'<span style="color:{col};font-weight:700;margin-right:8px">{html.escape(ev)}</span>'
        f'{extra}</div>'
    )

gen = time.strftime("%Y-%m-%d %H:%M:%S")
page = f"""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zolander verify — snapshot</title></head>
<body style="margin:0;background:#0b0d12;color:#e5e7eb;font:13px/1.5 ui-monospace,Menlo,monospace">
<div style="position:sticky;top:0;background:#12151d;border-bottom:1px solid #262b36;padding:10px 16px">
<div style="font:15px/1.4 -apple-system,sans-serif;font-weight:700">ZOLANDER · verify snapshot</div>
<div style="color:#9ca3af;font-size:12px;margin-top:2px">zmrazeny stav · {gen} · udalosti: {len(rows)} · block: {counts['block']} · pass: {counts['pass']} · error: {counts['error']}</div>
<div style="color:#6b7280;font-size:11px;margin-top:2px">zive okno: http://127.0.0.1:8790 (len na Macu)</div>
</div>
<div style="padding:8px 12px">{''.join(items) or '<div style="color:#6b7280;padding:20px">zatiaľ žiadne udalosti — MoA sa spustí pri ďalšom edite</div>'}</div>
</body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(page)
print("OK", OUT, len(rows), "udalosti")
