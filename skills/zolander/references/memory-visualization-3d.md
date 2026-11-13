# 3D vizualizacia Lorentz pamate (nas mozog) — OVERENE 2026-08-14

Ked veducko chce "vidiet nas mozog / mapu pamate / sietovy graf myslienok" (inspiracia
napr. semantica-agi/semantica UI): NEPOUZIVAJ cudzi stack, postav standalone HTML nad
NASIMI datami. Hotovy artefakt: `~/projects/zolander/viz/mozog.html` (self-contained,
ziadna nova zavislost v Zolanderovi).

## PRECO NIE semantica (a podobne)
- semantica-agi/semantica je enterprise KG/compliance platforma:
  RDF/LPG store, SHACL/OWL governance, PROV-O audit traily. Ta pekna 3D siet co veducko
  videl je LEN jedno okno (Knowledge Explorer) postavene na **Sigma.js = 2D WebGL** (nie
  prave 3D s rotaciou v priestore) + ForceAtlas2. Natlacit nasu 129D hyperbolicku pamat do
  ich euklidovsko/grafoveho modelu zabije prave tu hodnotu (hierarchia sedi v zakriveni).
- My data UZ mame (327 spomienok v mem_index.jsonl). Na peknu siet staci ~200 riadkov HTML,
  nie cely cudzi framework co treba zivit.

## GEOMETRIA — povedz veduckovi pravdu (chytil ma na "guli")
- Lorentz model NIE je gula. Je to **horny list dvojdielneho hyperboloidu** = miska/kuzel:
  <x,x>_L = -1, x0>0. Vrchol misky = najabstraktnejsie (r=acosh(x0)~0), cim dalej od
  vrcholu tym hlbsie/specifickejsie. Preto L2/L3 abstrakcie maju mensi r nez L0.
- 129D sa NEDA vykreslit -> projekcia do 3D (PCA). Dve poctive mapy toho isteho priestoru:
  - MISKA (hyperboloid): spatial PCA -> (x,y), z-os = x0 (hlbka od vrcholu). Verny tvar.
  - GULA (Poincare ball): p = x_spatial/(1+x0), potom PCA 3D. Klasicky "mozog v guli".
  Obe su matematicky ekvivalentne (ina mapa), daj PREPINAC miska<->gula (veducko chcel oboje).

## RECEPT (4 kroky, ~5 min)
1. Vstup: z `state/mem_index.jsonl` vytiahni {id,text} (dedup podla id, keep last) +
   meta {kind,layer,salience,text[:200]} do /tmp. 327 zaznamov, kindy: semantic/procedural/
   episodic/identity; layers skoro cele L0 (abstrakcny stroj off).
2. Re-embed: `.venv-yar/bin/python toolkit/embed_yar.py < in.jsonl > vec.jsonl` (129D Lorentz,
   ~2/s ~3min). POZOR: vektory sa z DB NEDAJU citat (getPoints halucia NOT_FOUND) -> VZDY
   re-embed z textov. Over `pgrep -f embed_yar` prazdne pred spustenim (race na vystupny subor).
   Bezi na pozadi (background+notify_on_complete).
3. Projekcia (venv-yar, ma numpy): parsuj len riadky s len(vector)==129. Hrany = kNN v
   **Lorentzovej vzdialenosti** (NIE euklidovej — to je pointa): d=arccosh(clip(-<x,y>_L,1,inf)),
   <x,y>_L = -outer(x0,y0)+S@S.T. K=3 -> ~758 hran pri 327 nodoch. Node: farba=kind, val=salience,
   ulozit obe pozicie (bowl, ball). Skala rozptylu ~110, nody male (val=0.6+sal*2.2) inak sa
   zlepia do blobu.
4. HTML: 3d-force-graph (three.js) z CDN unpkg.
   ⚠️ OPRAVA 2026-08-14 (veducko ma opravil "velke gule bez prepojeni"): NEVYPINAJ force
   engine a NENATLACAJ PCA pozicie ako FIXNE (fx/fy/fz). To robi obrie zlepene gule, hrany
   za nimi neviditelne = amatersky blob. (Predosla verzia tohto receptu radila charge/link/
   center=null + fx/fy/fz — to bolo ZLE, ignoruj.) Spravne: nechaj engine BEZAT (warmupTicks
   ~90, cooldownTicks ~220), nody len SEED-ni z projekcie (n.x/y/z, NIE fx/fy/fz),
   enableNodeDrag(true). Nasu 129D Lorentz matematiku pusti dnu cez VAHY HRAN, nie rucne
   pozicie: `d3Force('link').distance(l=>hyperbolicka_vzdialenost).strength(l=>blizkost)` +
   charge ~ -50. Bliz. spomienky = kratsia+silnejsia hrana -> engine ich stiahne sam.
   Prepinac gula/miska = re-seed n.x/y/z + `Graph.d3ReheatSimulation()` + zoomToFit.
   Hover tooltip = text spomienky. Checkbox auto-rotacia, checkbox slabe geo-vazby.

## PITFALLS (nachytali ma)
- `\u....` escapy v STATICKOM HTML tele (nadpis, labels) sa NEDEKODUJU — zobrazia sa doslova
  "Zolander \u2014 mozog". V JS stringoch (template literals) funguju, v HTML tele NIE. Ries:
  reálne UTF-8 znaky priamo, alebo `\u` len vnutri <script> JS retazcov. (Python: escapes v
  '''...''' sa spracuju pri zapise, takze \u2014 -> em-dash v subore = OK; problem bol ked som
  chcel emoji cez surrogate pary \ud83e\udd63 co v HTML tele ostali doslovne.)
- Nody prilis velke -> zlepeny blob, tvar misky ani hrany nevidno. Zmensit val + zvacsit
  rozptyl skaly (SC~110).
- VZDY over naostro v browseri (browser_navigate file:// + browser_vision + klik prepinaca),
  neslubovat "malo by fungovat". Zistenie z realnych dat: kindy sa geometricky ODDELUJU
  (identita drzi vlastny zhluk) aj ked je pamat skoro cela plocha L0 -> Lorentz nesie strukturu.
- mem_edges.jsonl (zol_graph realne hrany) casto NEEXISTUJE (dream este nenavesil parent/related,
  abstrakcny stroj off) -> nemozes stavat viz striktne nad zol_graph, dostanes 327 osamelych
  bodiek. Preto kNN z geometrie. Ked dream doplni hrany, prekresli ich ako samostatnu vrstvu.

## AKTUALIZACIA 2026-08-14 — REALNE hrany + laloky (po backfille 329 zaznamov)
Ked mem_edges.jsonl UZ existuje (backfill/dream navesil related), kresli REALNE vazby, nie
len geometricku kNN vypln:
- Hrany: precitaj `state/mem_edges.jsonl` ({from,to,edge,ts}; edge=parent|related|supersedes).
  Real hrany jasne/hrube, parent BIELE a najhrubsie (strecha), geometricke kNN len ako slabe
  modraste pozadie (checkbox na vypnutie). Priznak l.real na rozlisenie v linkColor/linkWidth.
- Laloky (komunity) = `/usr/bin/python3 toolkit/zol_graph.py communities <min>` (deterministicke,
  suvisle komponenty nad related hranami, zoradene density). Farbi nody podla komunity; prepinac
  FARBA: laloky(temy) <-> typ pamate. Komunity >=3 clenov dostanu vlastnu farbu, zvysok sivy.
- INTERPRETACIA (F11): sive osamele nody = spomienky bez related hrany (prah 0.70 konzervativny,
  graf rastie pomaly) = VERNE, nie bug. Homogenna/mlada pamat = jeden husty oblak, malo lalokov;
  zmerane std Lorentz vzdialenosti ~0.136 (skoro vsetko rovnako daleko). Identita jediny typ s
  intra<inter (tesnejsi lalok). NEZAPINAJ abstrakcny stroj kvoli krajsiemu obrazku — riziko
  autoimunitnej otravy (pokazeny L2/L3 sa vstrekuje cez hook_recall) + na homogennych datach
  vyrobi prazdne pseudo-laloky. Dry-first + empiricky re-test.

## PASCA — `process wait` klame pri redirect do suboru (OVERENE 2026-08-14)
Background proces s `> out.jsonl` (embed_yar): nastroj process(action=wait) vrati "exited"/
"completion_reason exited" HOCI proces STALE bezi (vystup nejde cez pty, tak wait nevidi zivot).
NEVER mu ver. Over realne: `pgrep -f embed_yar` (bezi?) + `wc -l out` (kolko hotovych). Az ked
pgrep prazdny A wc == pocet zaznamov, je hotovo. (sandbox: `sleep N; wc` = retazenie zakazane,
jeden atomicky prikaz — sleep zvlast, wc zvlast.)

## REGEN po zmene pamate
Skript nie je (staticky snapshot, ziadny daemon, nekafre do pamate/druhej session). Postup na
prekreslenie: (1) export id+text z mem_index -> /tmp vstup + meta, (2) embed_yar background, over
pgrep+wc, (3) precitaj mem_edges.jsonl + zol_graph communities, (4) PCA obe projekcie + JSON
{nodes,links,stats}, (5) vloz do HTML template + browser_navigate file:// + browser_vision over.
Ak veducko bude chciet "na jeden prikaz", sprav `viz/regen.py` (venv-yar, subprocess na zol_graph).

## VARIANT 2 — jednoprikazovy REGEN SKRIPT `gen_pamat_3d.py` (KUZEL, OVERENE 2026-08-15)
Toto UZ JE ten "na jeden prikaz" regen (nahradza "zatial nerobene" vyssie). Iny, jednoduchsi
render nez mozog.html: raw Three.js (importmap z unpkg, NIE 3d-force-graph) — kuzel/hyperboloid
kde x0 je VYSKA. Skript: `~/projects/zolander/toolkit/gen_pamat_3d.py`, vystup
`state/reports/pamat3d.html`. Spustenie:
  `/Users/__USER__/projects/zolander/.venv-yar/bin/python toolkit/gen_pamat_3d.py 2>/dev/null`
Cely pipeline (nacita mem_index.jsonl -> embed_batch cez YAR -> geometria -> zapis HTML) je
V JEDNOM python subore, ziadne /tmp medzikroky, ziadny background+pgrep tanec. ~415 faktov, pár min.

GEOMETRIA (kuzel = verny Lorentz): vyska y = arccosh(clip(x0,1,inf)) (hlbka na hyperboloide,
normalizovana na ~6); rovina (x,z) = PCA 128 priestorovych zloziek (SVD, skala ~6). Hrany kNN
v Lorentzovej vzdialenosti: inner=outer(x0,x0)-G@G.T; D=arccosh(clip(inner,1,inf)); K najblizsich.

KOREKCIE VEDUCKA (2026-08-15, "strasne velke gulicky a malo prepojeni... rychlo samo rotovat
a byt mobile friendly") — vsetky uz v skripte, drz ich pri kazdej dalsej viz:
- MALE gulicky: scale = 0.045 + salience*0.10 (NIE 0.09+s*0.22 — to boli "obrie blob" gule).
- MALO/CISTYCH hran: K=2 najblizsi susedia (nie 3+), tenke opacity~0.28 tlmene. Viac = chaos.
- RYCHLA AUTOROTACIA: OrbitControls autoRotate=true, autoRotateSpeed~2.2. Ked user chytí/tahá,
  `ctrl.addEventListener('start', ()=>autoRotate=false)`; dvojklik/dvojtuk = toggle rotacie.
- MOBILE: `pixelRatio=Math.min(devicePixelRatio,2)` (necap = zozerie mobilnu GPU), menej segmentov
  na gulu (SphereGeometry(1,10,10)), enablePan=false, touchstart -> pick(text tooltip),
  touchend s <300ms = dvojtuk toggle. viewport meta uz v <head>.

PASCA — YAR progress bar zaplavi stdout (OVERENE 2026-08-15): embed cez YAR pri kazdom behu
vypluje MEGA "Loading weights: ...%" progress bar (desiatky tisic znakov) do stderr/stdout ->
zahlti output tool-u. VZDY spustaj s `2>/dev/null` (chyby modelu nechces aj tak, realny vysledok
je posledny riadok "OK <path> <N> bodov"). Bez toho dostanes 80k znakov smetia namiesto vysledku.

## VARIANT 3 a 4 — presunute mimo tohto repa
Mapa knihy, kombinovany pohlad pamat+kniha a cross-mosty pamat<->kniha patria side projektu
nad separatnou knihou a boli presunute do samostatneho repa. Tu ostava len vizualizacia
samotnej pamate (varianty 1 a 2 + 2D prehlad nizsie).

2D TEXTOVY PREHLAD (nie 3D, ked veducko chce len "vypis co mas v pamati" ako HTML report):
`toolkit/gen_pamat_html.py` -> `state/reports/pamat.html` = karty faktov grupovane podla kind
(identity/procedural/semantic/episodic), zoradene salience, farebne taby. Cita PRIAMO
mem_index.jsonl (ziadny re-embed, /usr/bin/python3 stdlib, rychle). Doplnok ku 3D viz.

CESTA-MIGRACIA pasca: skript pouziva `ROOT = ~/projects/zolander` (NIE stary ~/zolander).
Ked ho vytvaras/kopirujes cez file tool do stareho ~/zolander/toolkit, funguje aj tak (cesty
su absolutne dnu), ale PATRI do ziveho `~/projects/zolander/toolkit/`. embed_yar import ide cez
`sys.path.insert(0, ROOT+"/toolkit")`.
