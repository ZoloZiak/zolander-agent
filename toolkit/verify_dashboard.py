#!/usr/bin/env python3
"""verify_dashboard.py — zive diagnosticke okno pre MoA pre-verify hook.

Cita ~/projects/zolander/logs/verify.jsonl a servuje HTML dashboard co sa
auto-refreshuje (fetnevhodnee /events kazde 2s). Zobrazuje kazdy krok hooku:
fired / mechanical_block / moa_start / moa_file (skore per model) / moa_pass /
moa_block / moa_error / moa_disabled.

Spustenie:
  /usr/bin/python3 ~/projects/zolander/toolkit/verify_dashboard.py [port]
Default port 8790. Otvor http://127.0.0.1:8790 .
Ciste stdlib (http.server), ziadne zavislosti, ziadny build.
"""
import sys
import os
import json
import http.server
import socketserver

LOG = os.path.expanduser("~/projects/zolander/logs/verify.jsonl")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8790

PAGE = """<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zolander — verify diagnostika</title><style>
*{box-sizing:border-box}
body{margin:0;background:#0b0d12;color:#e5e7eb;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
header{position:sticky;top:0;background:#12151d;border-bottom:1px solid #262b36;padding:10px 16px;z-index:5}
h1{margin:0;font-size:15px;font-family:-apple-system,sans-serif}
.sub{color:#9ca3af;font-size:12px;margin-top:2px}
.ctl{margin-top:8px;font-size:12px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.ctl label{color:#cbd5e1}
#stats span{margin-right:12px}
#log{padding:8px 12px}
.row{padding:5px 10px;margin:4px 0;border-radius:6px;border-left:3px solid #333;background:#12151d;white-space:pre-wrap;word-break:break-word}
.ts{color:#6b7280;margin-right:8px}
.ev{font-weight:700;margin-right:8px}
.fired{border-left-color:#3b82f6}.fired .ev{color:#3b82f6}
.moa_start{border-left-color:#8b5cf6}.moa_start .ev{color:#8b5cf6}
.moa_file{border-left-color:#06b6d4}.moa_file .ev{color:#06b6d4}
.moa_pass{border-left-color:#16a34a}.moa_pass .ev{color:#16a34a}
.moa_block{border-left-color:#dc2626}.moa_block .ev{color:#f87171}
.mechanical_block{border-left-color:#dc2626}.mechanical_block .ev{color:#f87171}
.moa_error{border-left-color:#ca8a04}.moa_error .ev{color:#eab308}
.moa_disabled,.moa_skip{border-left-color:#4b5563}.moa_disabled .ev,.moa_skip .ev{color:#9ca3af}
.k{color:#94a3b8}
</style></head><body>
<header><h1>ZOLANDER · MoA pre-verify diagnostika</h1>
<div class="sub">zive okno · log: ~/projects/zolander/logs/verify.jsonl</div>
<div class="ctl">
  <label><input type="checkbox" id="auto" checked> auto-refresh 2s</label>
  <label><input type="checkbox" id="tail" checked> auto-scroll</label>
  <span id="stats"></span>
</div></header>
<div id="log"></div>
<script>
let seen=0;
const box=document.getElementById('log');
function fmt(r){
  const div=document.createElement('div');
  div.className='row '+(r.ev||'');
  let extra='';
  for(const k in r){if(k==='ts'||k==='ev')continue;
    let v=r[k]; if(typeof v==='object')v=JSON.stringify(v);
    extra+=' <span class="k">'+k+'=</span>'+v;}
  div.innerHTML='<span class="ts">'+(r.ts||'')+'</span><span class="ev">'+(r.ev||'?')+'</span>'+extra;
  return div;
}
async function poll(){
  if(!document.getElementById('auto').checked)return;
  try{
    const res=await fetch('/events?from='+seen);
    const data=await res.json();
    if(data.rows&&data.rows.length){
      for(const r of data.rows)box.appendChild(fmt(r));
      seen=data.total;
      if(document.getElementById('tail').checked)window.scrollTo(0,document.body.scrollHeight);
    }
    document.getElementById('stats').innerHTML=
      '<span>udalosti: '+data.total+'</span>'+
      '<span>block: '+data.counts.block+'</span>'+
      '<span>pass: '+data.counts.pass+'</span>'+
      '<span>error: '+data.counts.error+'</span>';
  }catch(e){}
}
setInterval(poll,2000); poll();
</script></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # ticho

    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE, "text/html")
            return
        if self.path.startswith("/events"):
            frm = 0
            if "from=" in self.path:
                try:
                    frm = int(self.path.split("from=", 1)[1].split("&")[0])
                except Exception:
                    frm = 0
            rows = []
            counts = {"block": 0, "pass": 0, "error": 0}
            total = 0
            try:
                with open(LOG, encoding="utf-8") as f:
                    lines = [l for l in f if l.strip()]
                total = len(lines)
                for l in lines:
                    try:
                        r = json.loads(l)
                    except Exception:
                        continue
                    ev = r.get("ev", "")
                    if ev in ("moa_block", "mechanical_block"):
                        counts["block"] += 1
                    elif ev == "moa_pass":
                        counts["pass"] += 1
                    elif ev == "moa_error":
                        counts["error"] += 1
                for l in lines[frm:]:
                    try:
                        rows.append(json.loads(l))
                    except Exception:
                        pass
            except FileNotFoundError:
                pass
            self._send(200, json.dumps({"rows": rows, "total": total, "counts": counts}))
            return
        self._send(404, "{}")


def main():
    with socketserver.TCPServer(("127.0.0.1", PORT), H) as httpd:
        print(f"verify dashboard -> http://127.0.0.1:{PORT}  (log: {LOG})")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
