# zol_graph — priebežné linky + sen nad grafom + iniciatíva z konsolidácie (B/C/D, 2026-08-14)

Kontext: zol_graph.py bol postavený 2026-08-14 ráno, ale `stats` hlásil edges_total=0.
Nebol to bug — hrany tvoril LEN ascend pri tvorbe nového abstraktu, a od zapojenia ešte
nezbehol dream + na vyšších priečkach málo zdrojov. Vedúcko zadal víziu: linkovanie nech
je PRIEBEŽNÉ (lacné metadáta, netreba naň sen), a sen nech robí hodnotné: konsolidáciu
"on the top" nad už prepojenou pamäťou + kŕmi iniciatívu ("ako keď človek cez noc dostane
nápad"). Implementované celé B→C→D, otestované naostro. Súbory: zol_graph.py, zol_mem.py,
zolander_dream.py, initiative.py (živý strom, NIE git).

## Tichá diera nájdená pri tom (OPRAVENÁ)
Denná konsolidácia L0→L1 v `zolander_dream.dream()` NElinkovala vôbec — parent hrany
vytváral len ascend (L1→L2→L3). `consolidate()` už `from_ids` v každom dicte nesie, tak
fix je triviálny: po `remember_l1` navesiť `zol_graph.link(i, nid, "parent")` pre každý
zdroj. Graf odteraz rastie na VŠETKÝCH priečkach. POUČENIE: keď pridáš graf do jednej
vetvy pipeline (ascend), skontroluj VŠETKY vetvy čo tvoria uzly (aj dennú konsolidáciu).

## B — priebežné 'related' hrany v zol_mem.cmd_remember
- Prepájanie = metadáta, nemá čakať na 3:00. V remember: cez UŽ spočítaný Gemma vektor
  (`gvec` z dual-write do zol_mem_gemma) sa nájdu blízke záznamy a navesí 'related' hrana.
  ŽIADNY extra embed call, ŽIADNA extra latencia — vektor aj tak vzniká.
- PREČO Gemma a NIE YAR: YAR Lorentz dáva parafráze d~1.0 == nesúvisiacemu faktu d~0.99
  → pre 'related' NEPOUŽITEĽNÁ (len near-exact/supersede). Gemma cosine je jediný spoľahlivý
  sémantický lens (0.67 vs YAR 0.38).
- PREČO je bezpečné pridať prácu do remember: remember beží na POZADÍ (dream/writeback),
  NIE na štarte session (tam beží recall cez hook_recall). Takže +práca nezhorší "gateway
  nereaguje" / 429. (Toto vyvracia moju predošlú obavu — over KTORÝ príkaz beží na hooku.)
- Prah 0.70 = KALIBROVANÝ NAOSTRO (nie od oka): zmerané cosine na reálnych pároch v
  zol_mem_gemma. d<0.65 realne súvisiace (2 zázn. o HyperspaceDB d=0.45; "veducko" oslovenie
  d=0.60), d~0.85-0.95 voľne príbuzné, d>1.0 rôzne témy = šum. Konzervatívne = radšej menej
  ale reálnych hrán. Vypnuteľné ZOL_GRAPH_RELATED=0, ZOL_GRAPH_RELATED_THR, ..._MAX (3).
- POZOR — prah 0.70 chytá len SKORO-parafrázy (rovnaký aspekt), NIE širšiu tematickú
  príbuznosť. Zmerané: "analóg gabber setup" vs "gabber kopák distorzia" mali d~1.09 →
  nenalinkovali sa. Dôsledok: graf porastie POMALY, sen nad grafom sa naplno rozbehne až
  keď pribudne dosť blízkych záznamov. Kto chce hustejšie rýchlejšie: zdvihnúť THR na ~0.95
  za cenu občasného šumu. Alebo jednorazový backfill (nižšie).
- Fail-open overený: s vypnutou Gemmou sa záznam uložil bez pádu, bez related.

## C — sen konsoliduje NAD grafom (zol_graph.communities + dream.consolidate_graph)
- `zol_graph.communities(min_size, edge="related")` = deterministicky (bez LLM) nájde husto
  prepojené KOMUNITY (súvislé komponenty BFS nad related hranami), zoradí podľa density
  = hrany/uzly. Vracia {members, edges, density, has_parent}.
- dream po ascende spustí `consolidate_graph()`: komunita related uzlov = vznikajúca TÉMA
  naprieč vrstvami; z hustej komunity (density>=1.0) BEZ strechy vydestiluje 1 abstrakt
  (Opus, reuse `_distill_group`) a nalinkuje členov parent hranou. To je "on the top" —
  nie stúpanie po fixných vrstvách, ale syntéza nad tým, čo si pamäť sama uplietla.
- POISTKA (abstraction-engine test, references/abstraction-engine-empirical-test.md):
  NIKDY nespúšťať LLM na riedkej skupine → prázdny pseudo-princíp. Preto density prah +
  preskočenie komunít čo už majú strechu (has_parent >= members) = zároveň IDEMPOTENCIA
  (druhý beh vráti [], nič sa neduplikuje — dokázané naostro).
- Robustnosť overená: Opus pri destilácii SÁM ignoroval šumové uzly čo do komunity natiekli
  pri (testom) uvoľnenom prahu — do textu abstraktu ich nezahrnul.

## D — iniciatíva čerpá z výstupu sna (initiative.fresh_abstractions + gather)
- `fresh_abstractions()`: čerstvé abstrakty (L1/L2/L3, posl. 3 dni z mem_index) + husto
  prepojené témy z grafu bez strechy. Vložené do `gather()` ako sekcia "CO SEN ZOSYNTETIZOVAL",
  DECIDE_SYSTEM prompt doplnený nech to Opus berie ako "čo mi cez noc docvaklo".
- DEĽBA PRÁCE, NIE duplikát: sen v noci upratie + nájde vzorce; iniciatíva z tých vzorcov cez
  deň navrhne akciu. Iniciatíva ostáva JEDINÝ systém čo navrhuje — NEpridávať druhý generátor
  nápadov do dreamu (liezli by si do kapusty na WhatsApp). Toto bola pôvodná otázka vedúcka
  ("nech sen dáva nápady") — správna odpoveď: nie nový generátor, ale iniciatíva číta sen.

## Backfill starých abstraktov — realita
- mem_index.jsonl from_ids NEUKLADÁ (idú len do DB meta cez `source`); DB getPoints padá
  NOT_FOUND (server bug, viď hyperspacedb-server-bugs.md). Preto spätné child→parent mapovanie
  starých abstraktov sa dá dohľadať LEN z ranných briefov (formát "id=N, z A,B,C"), a ten
  formát je len v novších briefoch. Z 15 starých abstraktov sa dali nalinkovať len 2 (347, 385).
  Poctivo to povedz — viac sa spätne nedá, neskúšaj znova.
- JEDNORAZOVÝ backfill related pre existujúcich ~329 záznamov: prejsť index, pre každý
  document-mode Gemma-search v zol_mem_gemma, navesiť related pod prahom 0.70. Symetrický dedup
  dvojíc (frozenset), preskoč existujúce hrany. Lacné, raz, naplní graf naraz. Dry-run najprv.
  SPRAVENÉ NAOSTRO 2026-08-14: výsledok 133 related + 9 parent hrán, `communities 3` následne
  našlo 7 hustých tém bez strechy (26-uzlová identita/zrkadlo density 1.77, 13-uzlová
  HyperspaceDB stack, zamknutý-Mac, Hermes-config, zolo2.0) — sen (C) aj iniciatíva (D)
  majú konečne potravu.
- PASCA (timeout pri backfille nad veľkým korpusom): prvý --commit zapísal len 54 z 132 —
  Gemma daemon TIMEOUTOVAL na časti záznamov pod záťažou (súbežný embed + GPU, urllib timeout
  15s). Tiché čiastočné chyby ("# id=N CHYBA: timed out"). FIX: zdvihnúť timeout na 30s +
  idempotentný re-run --commit (dedup preskočí hotové, dobehne timeoutnuté) → +79 = 133.
  LEKCIA (prenosná): keď skript ženie LLM/embed daemon nad veľkým korpusom, over VÝSLEDOK
  (`zol_graph.py stats`) proti dry-run plánu — NEver self-reportu "zapísané N". Rozdiel = tiché
  timeouty. Idempotentný re-run s dedupom dobehne čisto. Beh je pomalý (subprocess hs.mjs na
  každý záznam ~6-8 min/329) → spusti na pozadí s notify, nie foreground-blocking.
- Chýbajúce záznamy v zol_mem_gemma: staré spred zapojenia Gemmy tam dual-write nedostal
  (skript ich hlási "zaznamov NIE v zol_mem_gemma"). Doplň re-embed document-mode + hs insert.

## Gemma daemon DURABLE — tichá diera (VYRIEŠENÉ 2026-08-14)
gemma_embed_server (:8901, vMLX) spadol na Metal assertion ("Completed handler provided after
commit call") a NEBOL pod launchd → recall bežal bez 3. lens a B by bez neho NIČ nelinkoval.
KĽÚČOVÝ TWIST: plist UŽ EXISTOVAL v `deploy/pl.zolander.gemmaembed.plist` (KeepAlive=true,
RunAtLoad, port 8901, env HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE), len nikdy nenaloadovaný do
~/Library/LaunchAgents/. INŠTALÁCIA (spravené naostro, každý príkaz atomicky = sandbox):
  # 1. najprv ZABI ručný proces čo drží :8901 (inak si launchd port nenabehne)
  cp deploy/pl.zolander.gemmaembed.plist ~/Library/LaunchAgents/
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/pl.zolander.gemmaembed.plist
Over: `curl -s http://127.0.0.1:8901/health` + `launchctl list | grep gemmaembed` (PID, exit 0).
KeepAlive=true ju reštartne pri ďalšom páde. Interpreter je vMLX
(/Users/__USER__/.local/share/uv/tools/vmlx/bin/python), NIE venv-yar (ten mlx_embeddings nemá).
POUČENIE (prenosné): keď je daemon "postavený" ale niečo naň nadväzuje TICHO zlyháva, over
`launchctl list` či VÔBEC beží pod launchd — plist v deploy/ ≠ nainštalovaný v LaunchAgents/.

## Testovacia disciplína pri tejto práci
- Retrieval/prah čísla VŽDY kalibruj naostro na DB (Gemma-search reálnych párov), NIE od oka.
- communities() otestuj najprv na SYNTETICKOM grafe (klika, riedka reťaz, malý komponent,
  has_parent) izolovane, potom end-to-end s reálnymi záznamami.
- Idempotenciu dokáž spustením 2× a porovnaním (druhý beh musí vrátiť []).
- Verifikačné skripty do state/ s prefixom hermes-verify-, MAŽ hneď po behu.
- Testovacie záznamy/hrany po sebe upratať z mem_index.jsonl + mem_edges.jsonl (DB body ostanú
  soft-deleted, neškodí). link(a, b, edge) — poradie args: from, to, TYP (nie a, edge, b).
