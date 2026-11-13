# 3D vizualizacia Lorentz pamate (nas mozog) — OVERENE 2026-08-14

Ked veducko chce "vidiet nas mozog / mapu pamate / sietovy graf myslienok" (inspiracia
napr. semantica-agi/semantica UI): NEPOUZIVAJ cudzi stack, postav standalone HTML nad
NASIMI datami. Hotovy artefakt: `~/projects/zolander/viz/mozog.html` (self-contained,
ziadna nova zavislost v Zolanderovi).

## PRECO NIE semantica (a podobne)
- semantica-agi/semantica je enterprise KG/compliance platforma ("open-source Palantir"):
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

## VARIANT 3 — MAPA KNIHY (nie pamate) `viz/gen_kniha_3d.py` -> `viz/kniha.html` (OVERENE 2026-08-15)
Ked veducko chce "vidiet knihu / mozog knihy / mapu naratívu" (NIE Zolanderovu pamat): postav
SAMOSTATNY snapshot nad kolekciou `lorentz129` (6110 atomov zolo2.0), NIKDY nemiesaj do zol_mem
(kniha = literarny material, mozog.html = zol_mem = Zolanderova identita; su to dve rozne veci).
Skript: `~/projects/zolander/viz/gen_kniha_3d.py`, spustenie
`~/projects/zolander/.venv-yar/bin/python viz/gen_kniha_3d.py 2>/dev/null`.

DATA (VSETKO UZ EXISTUJE — ZIADNY re-embed, na rozdiel od mozgu!):
- `~/projects/zolo2.0/work/ingest_vectors_yar.jsonl` — {id, vector[129]} YAR Lorentz, 6110.
- `~/projects/zolo2.0/work/ingest_meta.jsonl` — {id, gid, clean, category, ...}.
- `~/projects/zolo2.0/work/assignments_opus.jsonl` — {gid, theme(A-I), layer(L1-L4), conf}.
Pred stavbou skontroluj ci vektory uz su (glob work/*vec*/*lorentz*/*embed* + over vlen==129);
mozog re-embeduje z textov lebo DB vektory necitatelne, ale kniha ma ingest_vectors_yar.jsonl hotovy.

JOIN PASCA (nachytala ma — join dal 0 zaznamov): v `ingest_vectors_yar.jsonl` je pole "id" ale
je to realne GID (int 1..6110), NIE meta["id"] (ktore je STRING "ZivotnyPlan:2"). Kluc spravne:
vector["id"] == meta["gid"] == assignments["gid"]. Over prienik Pythonom (set(vids)&set(gids))
PRED stavbou, nie po. 5866/6110 ma temu (zvysok = META/vyradene -> theme "?").

GEOMETRIA (odlisna od mozgu — vyska NIE je x0 ale VRSTVA): y = LAYER_Y[layer] (L1=0 dole plytko
-> L4=6.6 hore); rovina (x,z) = PCA 128 priestorovych zloziek (SVD, skala ~9
nie 6, inak sa vrstva zlepi do dosky). Farba = 8 tem A-I (fixny dict). Hrany kNN K=2 v Lorentzovej
vzdialenosti. Vysledny tvar = 4 vodorovne vrstvy-pyramida (L1 siroka 3553 -> L4 uzka spicka 267),
presna "cibula podla hlbky". Prepinac farby TEMY<->VRSTVY. Render = raw Three.js importmap (ako
gen_pamat_3d.py): male gulicky scale=0.045+conf*0.10 setScalar(s) (NIE *3.2 — to bol blob co ma
nachytal; po korekcii vidno jednotlive body), autoRotate 2.2, mobile (pixelRatio cap 2,
SphereGeometry(1,10,10), enablePan=false, touch pick+dvojtuk toggle). gen_kniha_3d.py cita zolo2.0
-> SUKROMNY (nepushuj do verejneho repa, ako zol_book.py).

## VARIANT 4 — KOMBI `viz/gen_viz_all.py` -> `viz/viz.html` (pamat+kniha v JEDNOM, OVERENE 2026-08-16)
Ked veducko chce JEDEN subor s prepinacmi (nie zvlast mozog.html a kniha.html): `gen_viz_all.py`
spoji zol_mem (434) + lorentz129 (6110) do jednej sceny. Oba su YAR 129D Lorentz -> spolocny
priestor -> cross-hrany. DVA prepinace: DATASET (len kniha/len pamat/oboje) x RENDER (2 galaxie/
kuzel/gula/mozog). Vsetky 4 layouty sa RATAJU V PYTHONE do nd.P[render]=[x,y,z], JS len prehodi
pozicie + d3-free (raw Three.js importmap). Spustenie:
  ~/projects/zolander/.venv-yar/bin/python viz/gen_viz_all.py 2>/dev/null   (re-embed pamate ~3-4min)
- CONNECTOR = cross_edges(): pre kazdy mem najblizsi book v Lorentz vzdialenosti, cap 140 najsilnejsich.
  Vizual mostov, DATA SA NEMIESAJU (kniha ostava lorentz129, pamat zol_mem). To je F11-cisty "most".
  ⚠️ POZOR — YAR CROSS-MOSTY SU SEMANTICKY SUM (OVERENE 2026-08-16, vedúcko sa spytal "v com su
  prepojene" a mal PRAVDU ze v nicom): vytiahol som 8 najblizsich mostov z realnych dat — dvojice
  typu "korelacia != kauzalita" <-> "statocnost nie je darom prirody" = ZIADNY obsahovy suvis, a aj
  ten NAJBLIZSI most mal dist 0.804 (skala 0=totozne ~1=nesuvisiace) => ani jeden nie je realne
  blizky. Dovod: (1) YAR je slaby na vyznam (R@1 0.38, preto recall realne bezi na BM25+Gemma nie
  YAR); porovnat dva slabe YAR vektory z ROZNYCH korpusov = skoro nahodne pary co VYZERAJU ako veda.
  (2) pamat (fakty o systeme/userovi) a kniha (literarny material) sa obsahovo prekryvaju minimalne.
  NEPREDAVAJ tie mosty ako "kde pamat rezonuje s knihou" — to je efektna loz. Bud ich (a) zrus, alebo
  (b) HUD ich CESTNE oznaci "len blizkost v priestore, NIE obsahovy suvis, dist 0.80+" (spravene), alebo
  (c) prerob connector cez EmbeddingGemma (768D, gemma_embed_server) — az SILNY semanticky embed da most
  co realne znamena obsahovy suvis. Ak aj po Gemme vyjde malo mostov, to je PRAVDIVA odpoved (pamat a
  kniha su malo prepojene), nie bug na zakrytie.
  ✅ RIESENIE = HYBRID Gemma predfilter + OPUS reasoning (OVERENE 2026-08-16, vedúcko: "tak llm musi
  najst mosty" — mal PRAVDU, sedi so skill §10: relacny sud NIE je podobnost tvaru textu ale reasoning):
  ani cista Gemma to nezachranila (jej TOP par cos 0.736 "zdrzanlivost pred tvrdenim"<->"zakaz akcii
  pred likvidaciou pobocky" = zase sum; distribucia: p50 cos 0.53, len 56/434 nad 0.6). Preto:
  `toolkit/gemma_cross_llm.py` = FAZA1 embed oba korpusy cez gemma_embed_server :8901 (mode=document,
  cache state/gemma_vecs.npz, l2norm s osetrenim NULOVEHO vektora inak divide-by-zero + osetri knizne
  atomy <12 znakov), FAZA2 Gemma cosine top-K=8 kandidatov na spomienku, FAZA3 OPUS (llm_client
  chat, system=prisny posudzovatel, davka 6, resume cross_llm.progress) rozhodne ktory kandidat REALNE
  obsahovo suvisi -> {best_gid|null, strength, reason}. Prah MIN_STRENGTH 0.5. Vystup state/cross_bridges.json.
  VYSLEDOK: z 434 spomienok Opus potvrdil len 23 mostov (z povodnych 140 YAR-sumovych) — a TIE davaju
  zmysel (GrapheneOS<->hardened Android 0.9; boj proti entropii 0.85; "caja"=dievca 0.75; mikroplasty
  v tkanivach<->chemikalie 0.75). Malo mostov = VERNA mapa (pamat=prevadzka systemu, kniha=pribeh, malo
  sa prekryvaju), nie zlyhanie. gen_viz_all.py: load_llm_bridges() joinne cross_bridges.json cez
  mem_id->mem node + gid->book node, hrana=[i,j,1-strength,reason,strength]; JS EX nesie reason+strength,
  pick tooltip pri uzle ukaze "⚡ most (strength): reason". eCross~22. VZDY: gemma_embed daemon musi
  bezat (curl :8901/embed), Opus zadarmo davkuj. gemma_cross*.py citaju zolo2.0 -> SUKROMNE (nepushovat).
- VYBOJE (co veducko chcel, "elektricke prudy medzi neuronmi"): NIE gulicky posuvane po hrane
  Zmerane naostro cez Gemma (768D, gemma_embed_server :8901, oba korpusy mode=document, cosine):
  distribucia najlepsej podobnosti p50=0.526, p100=0.736, len 56/434 spomienok malo najblizsi atom
  nad 0.6. Gemma je jasne lepsia nez YAR v STREDE distribucie, ALE "top mosty" boli STALE sum:
  najsilnejsi par cos 0.736 = "zdrzanlivost pred tvrdenim" <-> "zakaz akcii pred likvidaciou pobocky"
  = ziadny suvis. Dovod je STRUKTURALNY, nie o kvalite embeddera: pamat=fakty o prevadzke systemu/
  userovi, kniha=pribeh — dva rozne svety, obsahovo sa skoro neprekryvaju; ziadny embedding
  nevyrobi most co tam nie je. VEDUCKO MAL PRAVDU: "llm musi najst mosty". Presne ako skill §10
  (ziak-local-ai-stack): priradenie temy/vztahu NIE je "podobnost tvaru textu" ale REASONING -> robi
  OPUS, nie embedder. SPRAVNY connector = HYBRID (rovnaky vzor ako recall): (1) Gemma predfilter
  top-K=8 kandidatov na spomienku (lacne, zuzi), (2) OPUS davka posudi ktory kandidat REALNE obsahovo
  suvisi (prisny system prompt, default null, sila 0-1 + dovod), (3) most = LEN Opusom potvrdeny par
  s jeho zdovodnenim v tooltipe, sila=jas/hrubka ciary. Nastroje (SUKROMNE, citaju zolo2.0):
  toolkit/gemma_cross.py (diagnostika distribucie), toolkit/gemma_cross_llm.py (hybrid, resumovatelny:
  gemma_vecs.npz cache + cross_llm.progress; llm_client.chat(system=...) davka 6, prah 0.5;
  osetruje divide-by-zero z prazdnych/kratkych textov -> l2norm s n[n==0]=1 + book min len 12).
  Vystup state/cross_bridges.json. PITFALL: prazdne/kratke texty daju nulovy Gemma vektor -> matmul
  divide-by-zero warning + falosne vysoke skore v top parov; filtruj kratke texty PRED embedom.
  POUCENIE (prenosne): ked "najblizsie" pary z embeddera nedavaju zmysel, NEZNIZUJ prah aby ich bolo
  viac — to je menej klamliva verzia toho isteho divadla. Bud connector zrus, alebo daj rozhodnutie LLM.
- VYBOJE (co veducko chcel, "elektricke prudy medzi neuronmi"): NIE gulicky posuvane po hrane
  (vedúcko to odmietol: "lietajuce gulicky, nie vyboje po kabloch"). SPRAVNE = svetelny ZABLESK
  s chvostom letiaci po kabli: kratky usek [t-TAIL, t] rozdeleny na SEG=7 dielikov, jas slabne po
  chvoste (pow((s+1)/SEG,1.7)), AdditiveBlending + depthWrite:false, VSETKY pulzy v JEDNEJ
  LineSegments geometrii (1 draw call, setDrawRange). Staticke kable stlm na opacity 0.22 nech
  ziari hlavne pulz. VYZNAM (vedúcko sa pytal "co to vizualizuje" — nesmie to byt cira ozdoba):
  pulz = "asociacia prave prebehla"; rychlost+jas ~ sila spojenia (str=1-w, blizsie=rychlejsie+
  jasnejsie); ZLTY pulz po cross-moste = spomienka rezonuje s myslienkou z knihy, modry=intra kniha,
  fialovy=intra pamat. POZOR: pohyblivy efekt sa na STATICKOM screenshote takmer neda overit —
  over layout/kable/farby vision-om, ale "ci to vyzera ako prud" posud vedúcko naostro v browseri.
- GALAXIE layout: kazdy dataset vlastna PCA3 *0.5 + posun po X (+-13). Kniha vpravo, pamat vlavo.
- MESH MOZOG (5. tvar, OVERENE 2026-08-16, vedúcko chcel "mesh mozgu"): body napchane do TVARU MOZGU.
  Poctivo mu POVEDZ ze je to KOZMETIKA — poloha uz nenesie Lorentz info (na rozdiel od ostatnych 4
  tvarov); HUD to aj pise "kozmetika, poloha nenesie dáta". Python layout: PCA3 mraku -> normalizuj
  do kocky -> radialne stiahnut do gule (u=c/|c|, rr=|c|^0.7) -> hemisfera podla ds (book=prava sign+1,
  mem=lava sign-1), elipsoid BRX3.4 BRY3.0 BRZ4.3, fisura FISS0.5. JS obal = proceduralne 2 hemisfery
  (SphereGeometry zdeformovana: gyri sinusy, splostit spodok y*0.82, x=sign*(|x|*0.94+0.42)),
  MeshStandardMaterial ruzovy opacity0.12 depthWrite:false DoubleSide. brainGrp.visible=(render==='mesh').
  ZIADNY externy GLB (shell-safe, offline). PITFALL: np.linalg.norm(c,axis=1,keepdims=True) da (m,1) ->
  rr[k2] pole nie skalar -> TypeError "only 0-dim arrays"; sploR na 1D (bez keepdims, u=c/r[:,None]).
  PITFALL2: FISS0.5 primala -> hemisfery splyvaju, pozdlzna ryha nie jasne vidno; ciste dve poloviny =
  zvacsi FISS. YAR progress bar ide na STDERR aj cez 2>/dev/null (80k smeti) — realny error = posledny Traceback.
- BLOB PASCA (nachytala aj tu, vedúcko ma na tom chytil uz 3x): prve gule 0.05+val*0.11 boli
  privelke -> zlepeny blob. OPRAVENE na 0.035+val*0.06 + galaxie offset 9->13, PCA *0.62->0.5.
  VZDY over vision po prvom rendri, guľky maju byt MALE bodky nie gule.
- gen_viz_all.py cita zolo2.0 -> SUKROMNY (nepushuj do verejneho repa, ako gen_kniha_3d.py).

2D TEXTOVY PREHLAD (nie 3D, ked veducko chce len "vypis co mas v pamati" ako HTML report):
`toolkit/gen_pamat_html.py` -> `state/reports/pamat.html` = karty faktov grupovane podla kind
(identity/procedural/semantic/episodic), zoradene salience, farebne taby. Cita PRIAMO
mem_index.jsonl (ziadny re-embed, /usr/bin/python3 stdlib, rychle). Doplnok ku 3D viz.

CESTA-MIGRACIA pasca: skript pouziva `ROOT = ~/projects/zolander` (NIE stary ~/zolander).
Ked ho vytvaras/kopirujes cez file tool do stareho ~/zolander/toolkit, funguje aj tak (cesty
su absolutne dnu), ale PATRI do ziveho `~/projects/zolander/toolkit/`. embed_yar import ide cez
`sys.path.insert(0, ROOT+"/toolkit")`.
