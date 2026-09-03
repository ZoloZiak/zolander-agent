#!/usr/bin/env python3
# 3D model Zolanderovej pamate: Lorentz hyperboloid -> kuzel.
# x0 (casova suradnica) = vyska; 128 priestorovych zloziek -> PCA -> (x,y) polomer.
# Body = fakty, farba = druh pamate. Vystup: samostatny HTML s Three.js (CDN).
import os, sys, json, math

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects/zolander")
IDX = os.path.join(ROOT, "state/mem_index.jsonl")
OUT = os.path.join(ROOT, "state/reports/pamat3d.html")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))

from embed_yar import embed_batch  # 129D Lorentz
import numpy as np

rows = []
with open(IDX, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("text"):
                rows.append(r)
        except Exception:
            pass

texts = [r["text"] for r in rows]
print(f"embedujem {len(texts)} faktov cez YAR...", flush=True)
vecs = embed_batch(texts)  # list[list[129]]
V = np.array(vecs, dtype=np.float64)      # (N,129)
x0 = V[:, 0]                              # casova suradnica (vyska hyperboloidu)
S = V[:, 1:]                             # (N,128) priestorove zlozky

# PCA priestorovych zloziek -> 2D (polomer roviny kuzela)
Sc = S - S.mean(axis=0)
U, sv, Vt = np.linalg.svd(Sc, full_matrices=False)
P = Sc @ Vt[:2].T                        # (N,2)

# normalizacia do peknej mierky
P = P / (np.abs(P).max() + 1e-9) * 6.0
# vyska: arccosh(x0) = hyperbolicka vzdialenost od vrcholu (hlbka)
h = np.arccosh(np.clip(x0, 1.0, None))
h = h / (h.max() + 1e-9) * 6.0

KIND_COLOR = {"identity": "#a855f7", "semantic": "#3b82f6",
              "procedural": "#16a34a", "episodic": "#ca8a04"}
KIND_LABEL = {"identity": "Identita", "semantic": "Fakty",
              "procedural": "Postupy", "episodic": "Udalosti"}

pts = []
for i, r in enumerate(rows):
    k = r.get("kind", "episodic")
    pts.append({
        "x": round(float(P[i, 0]), 3),
        "z": round(float(P[i, 1]), 3),
        "y": round(float(h[i]), 3),
        "c": KIND_COLOR.get(k, "#888"),
        "k": KIND_LABEL.get(k, k),
        "s": round(float(r.get("salience", 0.5)), 2),
        "t": r.get("text", ""),
        "id": r.get("id"),
    })

# --- HRANY: kNN cez Lorentzovu vzdialenost d = arccosh(-<x,y>_L) ---
N = V.shape[0]
G = V[:, 1:]
X0 = V[:, 0]
inner = np.outer(X0, X0) - (G @ G.T)          # = -<x,y>_L
np.clip(inner, 1.0, None, out=inner)
D = np.arccosh(inner)
np.fill_diagonal(D, np.inf)
K = 2                                          # max 2 najblizsi = malo prepojeni
edges = set()
for i in range(N):
    nn = np.argpartition(D[i], K)[:K]
    for j in nn:
        a, b = (i, int(j)) if i < int(j) else (int(j), i)
        if a != b:
            edges.add((a, b))
edges_list = [[a, b] for a, b in edges]

data_json = json.dumps(pts, ensure_ascii=False)
edges_json = json.dumps(edges_list)

html = """<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zolander — pamäť 3D (Lorentz kužeľ)</title>
<style>
 html,body{margin:0;height:100%;background:#08090d;color:#e5e7eb;font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}
 #hud{position:fixed;top:0;left:0;right:0;padding:12px 16px;background:linear-gradient(#08090dcc,#08090d00);z-index:10;pointer-events:none}
 #hud h1{margin:0;font-size:16px} #hud .s{color:#9ca3af;font-size:12px;margin-top:2px}
 #leg{margin-top:8px;display:flex;gap:14px;font-size:12px}
 #leg span{display:flex;align-items:center;gap:5px}
 .dot{width:10px;height:10px;border-radius:50%;display:inline-block}
 #tip{position:fixed;max-width:340px;padding:10px 12px;background:#161a22ee;border:1px solid #333;border-radius:8px;font-size:13px;line-height:1.45;pointer-events:none;opacity:0;transition:opacity .1s;z-index:20}
 #tip .m{font-size:11px;color:#9ca3af;margin-bottom:4px}
 #hint{position:fixed;bottom:12px;left:16px;color:#6b7280;font-size:12px}
</style></head><body>
<div id="hud"><h1>🧠 Pamäť Zolandera — Lorentzov kužeľ</h1>
<div class="s">__N__ faktov · výška = hĺbka na hyperboloide (arccosh x₀) · poloha = PCA priestorových zložiek · ťahaj myšou, koliesko = zoom</div>
<div id="leg">
 <span><i class="dot" style="background:#a855f7"></i>Identita</span>
 <span><i class="dot" style="background:#16a34a"></i>Postupy</span>
 <span><i class="dot" style="background:#3b82f6"></i>Fakty</span>
 <span><i class="dot" style="background:#ca8a04"></i>Udalosti</span>
</div></div>
<div id="tip"></div>
<div id="hint">ťuk/hover na guľôčku = text · dvojťuk = stop/štart rotácie</div>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script>
<script type="module">
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
const PTS = __DATA__;
const EDGES = __EDGES__;
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x08090d, 0.035);
const cam = new THREE.PerspectiveCamera(60, innerWidth/innerHeight, 0.1, 500);
cam.position.set(11,9,11);
const rnd = new THREE.WebGLRenderer({antialias:true});
rnd.setPixelRatio(Math.min(devicePixelRatio,2)); rnd.setSize(innerWidth,innerHeight);
document.body.appendChild(rnd.domElement);
const ctrl = new OrbitControls(cam, rnd.domElement);
ctrl.enableDamping=true; ctrl.target.set(0,3,0);
ctrl.autoRotate=true; ctrl.autoRotateSpeed=2.2;   // rychla auto-rotacia
ctrl.enablePan=false;
scene.add(new THREE.AmbientLight(0xffffff,0.75));
const pl=new THREE.PointLight(0xffffff,0.8); pl.position.set(10,15,10); scene.add(pl);
const grid=new THREE.GridHelper(16,16,0x1f2937,0x141a22); scene.add(grid);
// male gulicky (instanced pre vykon na mobile)
const geo=new THREE.SphereGeometry(1,10,10);
const meshes=[];
for(const p of PTS){
  const m=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color:p.c,emissive:p.c,emissiveIntensity:0.3}));
  const sc=0.045+p.s*0.10; m.scale.setScalar(sc);   // ovela mensie
  m.position.set(p.x,p.y,p.z); m.userData=p; scene.add(m); meshes.push(m);
}
// hrany (kNN Lorentz) — tenke, tlmene
const ep=[];
for(const [a,b] of EDGES){const A=PTS[a],B=PTS[b];ep.push(A.x,A.y,A.z,B.x,B.y,B.z);}
const eg=new THREE.BufferGeometry();
eg.setAttribute('position',new THREE.Float32BufferAttribute(ep,3));
scene.add(new THREE.LineSegments(eg,new THREE.LineBasicMaterial({color:0x3b4657,transparent:true,opacity:0.28})));
const ray=new THREE.Raycaster(); ray.params.Points={threshold:0.3};
const ptr=new THREE.Vector2(); const tip=document.getElementById('tip');
function pick(cx,cy){
  ptr.x=(cx/innerWidth)*2-1; ptr.y=-(cy/innerHeight)*2+1;
  ray.setFromCamera(ptr,cam); const hit=ray.intersectObjects(meshes)[0];
  if(hit){const d=hit.object.userData;
    tip.style.opacity=1; tip.style.left=Math.min(cx+12,innerWidth-320)+'px'; tip.style.top=(cy+12)+'px';
    tip.innerHTML='<div class="m">'+d.k+' · salience '+d.s+' · #'+d.id+'</div>'+d.t;
  } else tip.style.opacity=0;
}
addEventListener('mousemove',e=>pick(e.clientX,e.clientY));
rnd.domElement.addEventListener('touchstart',e=>{if(e.touches[0])pick(e.touches[0].clientX,e.touches[0].clientY);},{passive:true});
// dvojklik/dvojtuk = pauza rotacie
let lastTap=0;
function toggleRot(){ctrl.autoRotate=!ctrl.autoRotate;}
rnd.domElement.addEventListener('dblclick',toggleRot);
rnd.domElement.addEventListener('touchend',()=>{const t=Date.now();if(t-lastTap<300)toggleRot();lastTap=t;},{passive:true});
// pauza auto-rotacie kym uzivatel taha, potom obnov
ctrl.addEventListener('start',()=>ctrl.autoRotate=false);
addEventListener('resize',()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();rnd.setSize(innerWidth,innerHeight);});
(function loop(){requestAnimationFrame(loop);ctrl.update();rnd.render(scene,cam);})();
</script></body></html>"""

html = html.replace("__DATA__", data_json).replace("__EDGES__", edges_json).replace("__N__", str(len(pts)))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("OK", OUT, len(pts), "bodov")
