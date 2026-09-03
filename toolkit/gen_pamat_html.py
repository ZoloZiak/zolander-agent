#!/usr/bin/env python3
# generuje HTML report Zolanderovej YAR pamate z mem_index.jsonl
import json, os, html, datetime, collections

HOME = os.path.expanduser("~")
IDX = os.path.join(HOME, "projects/zolander/state/mem_index.jsonl")
OUT = os.path.join(HOME, "projects/zolander/state/reports/pamat.html")

rows = []
with open(IDX, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass

KIND_LABEL = {
    "identity": "Identita / hodnoty",
    "semantic": "Fakty / poznatky",
    "procedural": "Postupy / ako-na-to",
    "episodic": "Udalosti / zážitky",
}
KIND_COLOR = {
    "identity": "#a855f7",
    "semantic": "#3b82f6",
    "procedural": "#16a34a",
    "episodic": "#ca8a04",
}
ORDER = ["identity", "procedural", "semantic", "episodic"]

groups = collections.defaultdict(list)
for r in rows:
    k = r.get("kind", "episodic")
    groups[k].append(r)

for k in groups:
    groups[k].sort(key=lambda r: r.get("salience", 0), reverse=True)

total = len(rows)
gen = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def esc(s):
    return html.escape(str(s or ""))

parts = []
parts.append("""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zolander — pamäť</title><style>
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1115;color:#e5e7eb}
header{padding:18px 22px;background:#161a22;border-bottom:1px solid #262b36;position:sticky;top:0;z-index:5}
h1{margin:0;font-size:19px} .sub{color:#9ca3af;font-size:13px;margin-top:4px}
.tabs{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
.tab{font-size:12px;font-weight:700;padding:5px 11px;border-radius:20px;color:#fff;text-decoration:none;opacity:.9}
.sec{padding:8px 22px 4px} h2{font-size:15px;margin:18px 0 8px;display:flex;align-items:center;gap:8px}
.badge{font-size:11px;color:#9ca3af;font-weight:400}
.card{background:#161a22;border:1px solid #262b36;border-left-width:4px;border-radius:8px;padding:9px 12px;margin:7px 0}
.m{display:flex;gap:10px;align-items:center;font-size:11px;color:#8b93a1;margin-bottom:4px;flex-wrap:wrap}
.sal{font-weight:700}
.txt{color:#e5e7eb;font-size:14px}
.pill{font-size:10px;padding:1px 6px;border-radius:4px;background:#262b36;color:#cbd5e1}
</style></head><body>""")

parts.append(f"""<header><h1>🧠 Zolander — obsah pamäte (YAR zol_mem)</h1>
<div class="sub">{total} faktov · zdroj: state/mem_index.jsonl · zoradené podľa salience · generované {gen}</div>
<div class="tabs">""")
for k in ORDER:
    if groups.get(k):
        parts.append(f'<a class="tab" style="background:{KIND_COLOR[k]}" href="#{k}">{esc(KIND_LABEL[k])} ({len(groups[k])})</a>')
parts.append("</div></header>")

for k in ORDER:
    items = groups.get(k)
    if not items:
        continue
    col = KIND_COLOR[k]
    parts.append(f'<div class="sec" id="{k}"><h2><span style="color:{col}">●</span> {esc(KIND_LABEL[k])} <span class="badge">{len(items)} faktov</span></h2>')
    for r in items:
        sal = r.get("salience", 0)
        layer = esc(r.get("layer", ""))
        ts = esc((r.get("ts", "") or "")[:10])
        mid = esc(r.get("id", ""))
        txt = esc(r.get("text", ""))
        parts.append(f'<div class="card" style="border-left-color:{col}">'
                     f'<div class="m"><span class="sal" style="color:{col}">◆ {sal:.2f}</span>'
                     f'<span class="pill">{layer}</span><span>#{mid}</span><span>{ts}</span></div>'
                     f'<div class="txt">{txt}</div></div>')
    parts.append("</div>")

parts.append("<div style='height:40px'></div></body></html>")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(parts))
print("OK", OUT, total, "faktov")
