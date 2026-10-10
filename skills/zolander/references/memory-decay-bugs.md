# Salience decay / writeback / brief — tri pasce (OVERENE 2026-08-13)

Diagnóza spustená tým, že ranný brief `denniky/brief_<den>.md` navrhol na
zabudnutie ~180 spomienok naraz (celá dávka z 08-08 spadla na salience 0.0).
Nebolo to „180 nudných spomienok" ale ROZBITÝ decay čo zabíjal durable pamäť.

## BUG 3 (killer) — decay kompoundoval sám seba
Starý `cmd_decay` v `zol_mem.py` robil `new_sal = sal - rate*age_days` a
PREPÍSAL salience v `state/mem_index.jsonl`. Ďalšia noc prečítala už zníženú
hodnotu a odčítala `rate*PLNÝ_vek` ZNOVA. Fakt z 0.6, L0 rate 0.08/deň:
  noc1 0.52 → noc2 0.36 → noc3 0.12 → noc4 0.0 (exponenciálny pád)
  správne malo byť idempotentne: 0.6 − 0.08×5 = 0.2 (žije, nad prahom)
FIX: decay je IDEMPOTENTNÝ — počíta VŽDY z fixnej `base_salience`
(`current = base_salience − rate*age`), nikdy z už zdecayovanej hodnoty.
`cmd_remember` odteraz zapisuje `base_salience` do indexu pri vzniku riadku.

## BUG 2 — writeback sypal VŠETKO ako L0
`zol_writeback.py` ukladal aj `semantic`/`procedural`/`identity` fakty s
`layer="L0"`, a decay rátal rýchlosť podľa LAYER (L0=0.08/deň). Durable fakty
(sandbox pravidlá, agy-bridge, HyperspaceDB setup) tak decayovali ako pominuteľné
epizódy. FIX (dvojitý, aby jeden chránil druhý):
  (a) decay rýchlosť riadi teraz KIND, nie layer:
      KIND_DECAY = {identity 0.0, procedural 0.004, semantic 0.008, episodic 0.05}
  (b) writeback píše durable kindy ako L1, len episodic ako L0 (label konzistencia).
Forget sa navrhuje LEN pre episodic staršie ako 14 dní pod prahom 0.12 —
durable kindy sa na forget NIKDY nenavrhujú.

## BUG 1 — forget-zoznam bol slepý
`write_brief` písal holé `- [ ] id=42 — nízka salience` bez textu → nedalo sa
rozhodovať. FIX: `_index_text_map()` dolepí `[kind] text` z mem_index ku každému
id v denníku.

## Migrácia poškodeného indexu (jednorazovo, bezpečne)
`cmd_decay` pri chýbajúcom `base_salience` v riadku dopočíta base: ak je uložená
salience VÝRAZNE nižšia než očakávaná (poškodená bugom), obnoví base na
`KIND_BASE[kind]` (identity 0.9, procedural 0.8, semantic 0.7, episodic 0.5);
inak base = current + rate*age (spätný dopočet). Postup overenia naostro:
  1. záloha: `cp mem_index.jsonl mem_index.jsonl.bak-<den>`
  2. `$VPY zol_mem.py decay` → sleduj `migrated` count (koľko sa opravilo)
  3. `$VPY zol_mem.py decay` DRUHÝ raz → `migrated` MUSÍ byť 0 a forget stále []
     (to je dôkaz idempotencie — žiadne ďalšie kompoundovanie)
Výsledok 2026-08-13: 320 riadkov, migrated 254, forget 180→0.

## Testovanie decay logiky BEZ dotyku živej pamäte (prenosný recept)
Docasny harness `~/projects/zolander/state/hermes-verify-decay.py`: monkeypatch
`zol_mem.STATE = tempfile.mkdtemp()`, zapíš syntetické riadky do temp
`mem_index.jsonl`, spusti `cmd_decay()` s `contextlib.redirect_stdout`, čítaj
suggestions + prepísané riadky. Bež cez `.venv-yar/bin/python` (zol_mem
importuje torch pri loade). Pokry: idempotencia (3× beh), heal poškodeného,
zdravý sa neprepíše, starý episodic→forget, durable NIKDY forget (ani po 90d
na sal 0), identity nedecayuje, chýbajúci kind fallback, zlý ts nespadne,
hranica 14 dní, kept counter. ZMAŽ harness po behu (prefix hermes-verify-).
POZOR: vedúcko odmietne testovací `remember` do ŽIVEJ pamäte (blocked) — netreba,
izolovaný temp harness stačí a nič nezašpiní.

## POUČENIE (prenosné)
Každý decay/scoring proces čo PREPISUJE svoj vstup na mieste je podozrivý na
kompoundovanie — over idempotenciu spustením 2× za sebou a porovnaním výstupu.
Drž nemennú `base_*` hodnotu a odvodenú `current_*` počítaj z nej, nikdy z
predošlého current. A keď automat navrhne „zabudni skoro všetko“, nie je to šum
na odklikanie — je to symptóm rozbitého scoringu, hľadaj root cause.

## DORMANT NIE JE HARD—DELETE + orphan—safe detach (2026-09-27, OVERENÉ)
Decay iba PRESÚVA do dormant/retired — NIKDY nemže natvrdo z DB/indexu. GC (`zol_gc.py`)
sa týka len L2/L3, pamäť je celá L0 → GC je na ňu no-op. Čiže subor `mem_index.jsonl`
rastie donekonečna aj po dormante (283 dormant, 0 retired lebo najstaršie má 50d, prah
60d). „vyčistí sa to v noci samo?“ = NIE, samo z DB nezmizne.
- **Keď automat navrhne veľa forget-ov, NAJPRV over či scoring nie je rozbitý** (bug 3),
  až potom rieš. 2026-09-27: 283 dormant bolo KOREKTNÉ (všetko episodic >14d sal<0.12,
  durable sa nenavrhlo) — nie opakovanie bugu. Ale aj tak sa NEODKLIKÁVA hromadne: v
  zozname sú zdravotné/právne/zäväzkové epizódy čo vyzerajú „nudne“ ale nesmú zmiznúť.
- **Archivácia uzla vyžaduje ORPHAN-SAFE detach hrán.** 279/283 dormant má hrany (spolu
  ~1623). Soft-del bez čistenia hrán = 1623 orphanov (lekcia id=1078 na 28×). Dve cesty:
  1. `mem_store.delete(remove_index=True)` UŽ MÁ vstavaný orphan-clean (r.278-291, po bugu
     id=1078): keď uzol zmizne z indexu, jeho hrany sa auto-vyčistia. ALE nereverzibilne
     (hrany sa len zahodia, bez trash).
  2. `zol_graph.detach(dead_id, trash_path=...)` (nové, 2026-09-27) — čistý protejšok
     `reparent` pre prípad „uzol proste zmizne“ (bez keepera). Zmaže všetky hrany + uloží
     do JSONL trashu → REVERZIBILNÉ. Idempotentné. `zol_archive.py` ho volá PRED delete,
     aby bola celá archivácia vrátiteľná (record→archive, hrany→edge_trash, bod→dedup_trash).
- **TEST decay/archivácie BEZ dotyku živej pamäte:** `ZOLANDER_ROOT` presmeruje `zol_paths`
  a tým `mem_store`/`zol_mem` na kópiu, ALE `zol_graph` má STATE **hardcoded** (nie cez
  zol_paths) → env ho nepresmeruje. Pre graf test monkeypatchni `zol_graph.EDGES` na
  kópiu priamo. Overené B3 testom (15/15): detach 288 hrán→0 orphanov, archive apply na
  kópii s mock DB-delete, živý index mtime nezmenený. Bež cez `.venv-yar/bin/python -E`.
