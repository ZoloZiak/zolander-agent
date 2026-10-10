# Pamäť — recall aktuálny stav (YAR + BM25 + Gemma + rerank)

> Toto je operačný STAV recall vrstvy. Plán ďalšieho refaktoru (Gemma nahrádza YAR
> vo fúzii, YAR ostáva Lorentz kostra) je v `memory-refactor-2026-08.md`. DB serverové
> bugy v `hyperspacedb-server-bugs.md`. Bezpečnosť recallu v `memory-security-hardening.md`.

## Základ — YAR v5, JEDNA kolekcia
JEDNA HyperspaceDB Lorentz kolekcia `zol_mem` (migrácia 4→1, 2026-08-08; benchmark:
1 kol == 4 kol kvalitou, 4 kol 2.6-3.6× pomalšie). Druh pamäte je v meta poli
`memory_type` = semantic|episodic|procedural|identity. Embedding = natívny
hyperbolický YAR v5 (embed_yar.py), NIE EmbeddingGemma/cosine. Spúšťaj cez venv:

    VPY=/Users/__USER__/projects/zolander/.venv-yar/bin/python
    remember: echo '{"text":"...","kind":"semantic","layer":"L1"}' | $VPY toolkit/zol_mem.py remember
    recall:   echo '{"query":"...","topk":5}' | $VPY toolkit/zol_mem.py recall   (bez kind = všetky typy; kind="..." = filter memory_type)

Build-in Hermes pamäť drž minimálnu. Mazanie bodu: `node hs.mjs del zol_mem <id>`
(server soft-delete: count sa nemení hneď, ale recall zmazaný nevráti).

## DEDUP dvojvrstvový + pasce (OVERENÉ 2026-08-08)
(1) WRITE gate v remember = near-exact (d<0.15) sa NEuloží (YAR nevie parafrázy,
len presné kópie — napr. session 2×). (2) nočný dream loop = opus semanticky zlúči
parafrázy (toolkit/dedup_dream.py), auto-merge s recovery v state/dedup_trash.jsonl
+ audit v rannom briefe.
- (a) opus judge je NEDETERMINISTICKÝ — dva behy na tých istých dátach nájdu INÉ
  podmnožiny duplikátov; preto dedup NIE je „odklikni raz zoznam" ale postupný nočný
  proces (za pár nocí vyčistí, idempotentne + trash poistka). Neschvaľuj s vedúckom
  fixný zoznam párov vopred — kým odklikne, ďalší beh nájde iné.
- (b) dedup_dream.py MÁ stropy proti viseniu (po tom čo raz visel 25 min, D-state/
  zombie na gRPC del): _ask_opus max_retries=2 + SIGALRM 180s, _del_point timeout 30s
  s odchytením, dedup() wall-clock 600s, poradie del→trash (nie false recovery).
- (c) YAR NEODLÍŠI parafrázu od cudzieho textu (parafráza d~1.0 == nesúvisiaci fakt
  d~0.99) → kandidátov na sémantický dedup NEVYBERAJ vzdialenosťou, daj opusovi celý
  zoznam a nech rozhodne reasoningom.

## HYBRID RECALL — BM25 lexikálna poistka nad YAR (2026-08-13, OVERENÉ)
YAR 129D Lorentz je slabý na parafrázu (~52% namerané): fakt čo v pamäti JE sa cez
čisto semantický recall občas nevráti (real prúser: WhatsApp Zolander o izbách nevedel,
hoci id 383 tam bol). FIX: cmd_recall v zol_mem.py je HYBRID = YAR semantic + BM25 nad
mem_index.jsonl, zlúčené SCORE-FÚZIOU (min-max normalizácia oboch, váhy W_SEM=1.0 / W_LEX=1.3).
- BM25 modul: toolkit/mem_lexical.py (stdlib, bez GPU, diakritika sa foldu NFKD).
  Korpus = mem_index.jsonl; DB nemá listing a getPoints halucinuje NOT_FOUND.
- KĽÚČOVÁ LEKCIA: RRF (rank-based fusion) tu ZLYHAL — odmeňuje konsenzus, sumové záznamy
  stredne vysoko v OBOCH rebríčkoch predbehnú záznam so silným signálom v JEDNOM. Preto
  min-max SCORE fusion (zachytí veľkosť náskoku), NIE RRF. Keď druhý zdroj je slabý/
  nekonzistentný, RRF nepoužívaj.
- Vypnuteľné: obj["no_lexical"]=true / env ZOL_RECALL_LEXICAL=0. Fail-open (ak mem_lexical
  zlyhá, recall beží na čistom YAR). Výstup má pole "score" (fused), lexical_only:true =
  záznam našiel len BM25.
- Testy: toolkit/test_mem_lexical.py (7/7). POZOR: BM25 žiari na kľúčových slovách; na
  abstraktnú/parafrázovanú query bez zhody slov stále rátaš na (slabý) YAR.

## RECALL v3 — morfológia + plný text + LLM re-rank (2026-08-13, OVERENÉ)
1. SK/PL STEMMER (mem_lexical._stem): odseká pádové/číslo koncovky (min kmeň 3, slovanské
   slová sú krátke: izb-a). 'izba/izby/izbu' -> 'izb'; 'prenajom' -> 'prenaj'. BEZ neho
   BM25 netrafí jednotné číslo query proti množnému v texte. 10/10 testov.
   PASCA: min-kmeň 4 blokoval odseknutie 4-znakového slova -> izba/izby sa NEZLÚČILI.
   Znížené na 3 + otestované empiricky (nehádať).
2. PLNÝ TEXT: remember ukladá text[:300] do mem_index.jsonl (predtým [:120]). DB meta má
   tiež [:300]. (Staré riadky majú [:120], nové [:300].)
3. LLM RE-RANK (mem_rerank.rerank, Opus) — VOLITEĽNÝ. Zapína obj["rerank"]=true /
   env ZOL_RECALL_RERANK=1. Vezme top-8 z fúzie, Opus preusporiada podľa ZÁMERU. Fail-open.
   Overené naostro: "hladam izbu blizko roboty" -> #383 izby prvé. Výstup má "reranked":true.
   mem_rerank importuje palantir_client (chat) zo zolo2.0/toolkit.
PORADIE STAVANIA (nutnosť): plný text -> stemmer -> re-rank. Re-rank na odseknutých
útržkoch alebo zlých kandidátoch = piesok.

## RE-RANK SMART DEFAULT (2026-08-13) — ON pri hľadaní, OFF na štarte session
Re-rank DEFAULT ON pre priamy/interaktívny recall (aktívne hľadáš fakt, +8s nevadí),
session-start OFF. Priorita v cmd_recall: explicitný obj["rerank"] > env ZOL_RECALL_RERANK
> default ON.
- zol_session.py cmd_start posiela recall s "rerank": False -> hook_recall (CLI aj gateway)
  nabieha bez Opus callu. DÔVOD: session-start je o ŠÍRKE kontextu, nie dokonalom poradí;
  +8s/1 Opus call na KAŽDÝ nábeh gatewaya = vráti starý "nereaguje" neduh + prilieva do 429.
- Priamy `zol_mem.py recall` = rerank ON automaticky.
- TICHÁ REGRESIA: zol_session start formátoval f"{d:.3f}" na distance, ale lexical-only
  (BM25) záznamy majú distance=None -> TypeError -> spadlo do except. Fix: ak distance None,
  ukáž score (s=), inak d=. POUČENIE: keď zmeníš tvar výstupu (položky s None poľami),
  skontroluj VŠETKÝCH konzumentov, nielen hlavnú cestu.

## PAMAT v2 (2026-08-14): 3-lens kaskáda + graf + grounding
- RECALL = BM25 + YAR + EmbeddingGemma (min-max fusion, váhy 1.6/1.0/0.8) -> Opus rerank.
  Gemma cez perzistentný daemon gemma_embed_server :8901 (vMLX, drží GPU model), kolekcia
  zol_mem_gemma (768D cosine, SAMOSTATNÁ od Lorentz zol_mem — NEmiešať geometrie!).
  Všetko fail-open (ZOL_RECALL_GEMMA=0 vypne).
- POZOR EmbeddingGemma je ASYMETRICKÁ: bez prompt prefixov ("task: search result | query: "
  / "title: none | text: ") je retrieval ROZBITÝ. Padding musí byť DETERMINISTICKÝ
  (max_length), inak single vs batch dá iný vektor (~8% posun). Query mode=query,
  dokument mode=document.
- zol_graph.py: memory-to-memory hrany (parent/supersedes/related) + bitemporal. Detail
  receptu B/C/D + kalibrácia v `memory-graph-bcd.md`. Gemma daemon DURABLE pod launchd
  (pl.zolander.gemmaembed).
- LEKCIA: retrieval číslo VŽDY over naostro cez DB pred zapojením, nie len v numpy evale —
  0.891 z evalu bol artefakt chybného (bez-prefix) embeddingu; reálne Gemma pridá +0.004.

## EVAL RECALLU — zmerané, nie od oka (2026-08-14, 24 parafráz. otázok)
- mem_eval_goldset.py: Opus vygeneruje gold-set = realistické SK otázky PARAFRÁZOU záznamov.
  Ukladá state/mem_eval_gold.json (SÚKROMNÝ, tvoje spomienky).
- mem_eval.py: embed RAZ, sweep váhy W_LEX aritmetikou. Metriky Recall@1/3/5 + MRR.
VÝSLEDKY (R@1 / MRR) na korpuse 318 záznamov:
    yar_only      0.38 / 0.453   <- YAR SÁM slabý aj v praxi
    bm25_only     0.83 / 0.881   <- na malom korpuse robí ťažkú prácu lexika!
    hybrid W=1.3  0.83 / 0.876   <- sweet spot plateau W=1.0-1.6; W=1.3 optimum
    hybrid+rerank 0.92 / 0.938   <- Opus re-rank reálne pridáva +9 R@1 (ospravedlnené DÁTAMI)
KĽÚČOVÉ: (1) W_LEX=1.3 od oka VYŠLA ako optimum, ale AŽ TERAZ zmerané. (2) YAR pridáva k
BM25 málo; hlavná hodnota BM25 + re-rank. (3) re-rank jediná vec čo posunie R@1 nad 0.83
-> smart-default (ON pri hľadaní) je správny. NEZNIŽUJ W_LEX pod 1.0 (R@1 padne na 0.5-0.71).
- INICIATÍVNY EVAL WATCHER: toolkit/zol_eval_watch.py (durable launchd týždenne). Sám spustí
  mem_eval.py, zapíše MRR+corpus do state/eval_history.jsonl, pošle NÁVRH na WhatsApp LEN
  pri regresii MRR>=0.05 alebo raste korpusu>=60. Inak TICHO. Fail-open.
- Budúce vylepšenie (DDA/asociačný-kalkul paper): differentiation contract v BITOCH,
  cross-terms YAR×BM25, grounding salience — `memory-as-association-calculus.md`.
- Nástroje: mem_eval3.py, mem_diff.py, embed_gemma_corpus.py. Gemma LEN cez
  /Users/__USER__/.local/share/uv/tools/vmlx/bin/python (venv-yar mlx nemá).

## DORMANT GATE (A) + ARCHIVÁCIA (B) — zombie mimo recallu (2026-09-27, OVERENÉ)
Korpus narástol 318→2437 (98 % automatický writeback z coding session). Decay označil
283 starých epizód ako `forget_state=dormant` (salience 0), ale ostali fyzicky v indexe.
- **A — dormant sa NEPREHĽADÁVAJÚ ani NEINJEKTUJÚ (2 vrstvy, obe nutné):**
  1. `mem_lexical.load_corpus` preskočí dormant/retired (BM25 ich nevidí). Vypnuteľné
     `ZOL_LEXICAL_INCLUDE_DORMANT=1`.
  2. **KRITICKÉ:** BM25 filter sám NESTAČÍ. Semantic (hs search) + gemma vetvy vracajú
     dormant z DB s PLNÝM `meta.salience` (0.7–0.8) — **DB NEVIE o forget_state**, drží
     len STATICKÉ meta zo zápisu (dormant→salience 0 sa do DB nepremietne). Unified boost
     tak dormant NEUTLMÍ. Overené: pri topk=30 semantic vetva presla 3 dormant. FIX =
     jednotný gate `zol_mem._filter_dormant` PO fúzii, číta forget_state z mem_index
     (autoritatívny zdroj), NIE z DB meta. Vypnuteľné `ZOL_RECALL_INCLUDE_DORMANT=1` /
     obj['include_dormant']. Fail-open (bez mapy nefiltruje). PONČENIE: pri viac-vetvovom
     retrieval filter na jednej vetve nikdy nepostačí — gate daj na miesto kde sa vetvy
     zlievajú, a stav čítaj z autoritatívneho zdroja, nie z toho čo vráti DB.
- **A je recall-NEUTRAL na skóre** (+0.005 MRR = šum), a to je SPRÁVNE: gold targety sú
  active, filtrovanie dormant ich nemôže ovplyvniť. Hodnota A = ČISTOTA KONTEXTU (dormant
  sa neinjektujú), nie výkonový trik. Ak by A zmenila skóre, bol by to bug.
- **B — fyzická archivácia** (`toolkit/zol_archive.py`, DRY-RUN default): retired/dormant
  z indexu → `state/mem_archive.jsonl` + soft-del z DB. Reverzibilné. `plan`=dry-run,
  `apply --yes`=vykoná. Retired prah (decay: >60d & sal<0.05 & episodic) = dnes 0
  záznamov — B je poistka na rast súboru, NEspúšťaj naostro kým súbor reálne nezavadzia
  (2703 riadkov dnes nebrzdí nic). `--dormant-age N` pridá dormant staršie N dní na
  jednorazové upratanie. Orphan-safe cez `zol_graph.detach` (viz memory-decay-bugs.md).

## GOLD-SET DERAVÝ = EVAL JE KLAMSTVO (2026-09-27, DRÁH POCHOPENÉ)
Historické čísla (bm25 0.83, hybrid=bm25, YAR pridáva 0) boli na INOM menšom korpuse a
STAROM gold-sete — NEPOROVNATEĽNÉ s dneškom. Starý `mem_eval_gold.json` mal 8 z 24
targetov MŔTVYCH (5 id neexistuje po dedupe, 3 dormant) → strop evalu bol reálne
16/24, nie 1.0. Každé meranie na ňom bolo lžou.
- **PRED každým evalom over že gold targety sú `active` v mem_index** (dedup prečísluje
  ID; forget odkladá). Mŕtvy target = buď presmeruj na živý ekvivalent (rovnaký fakt
  pod iným id), alebo vyhoď. Záloha `.bak-<den>` pred zápisom.
- **KURATELA gold-setu NESMIE použíť recall engine** (embed→search) — to je cirkularita
  (testoval by si recall recallom). Presmerovanie na živý ekvivalent rozhodni z TEXTOV
  ručne / nezávislým úsudkom, nie token-overlapom ani search skóre.
- **REÁLNE ČÍSLA na čistom gold-sete (21 živých targetov, korpus 2437):**
      yar_only      R@1 0.33 / MRR 0.425   <- YAR sám stále slabý
      bm25_only     R@1 0.67 / MRR 0.706
      hybrid W=1.6  R@1 0.71 / MRR 0.727   <- hybrid > bm25, semantika pridáva ~4b R@1
  Na tomto (väčšom, šumnejšom) korpuse bm25 klesla z historických 0.83 na 0.67 a
  semantika už NIE je nula — vo fúzii reálne dvíha. "YAR = zbytočný prívesok" už NEPLATÍ
  tak tvrdo; sám je slabý (0.33), ale fúzia BM25+YAR+Gemma bije čistý BM25.
- **PONČENIE (prenosné):** predtým som TRIKRÁT predal predčasnú diagnózu ako istotu
  ("semantika mŕtva" → "A zlepší recall" → "A ublížila") — všetky vyvrátené meraním za
  minúty. Keď máš pod rukou eval, NEHÁDAJ smer — zmeř obe strany (A on/off) a nech
  rozhodnú čísla. A pozor na to ČO meríš: čiže najprv over že benchmark nie je sám
  rozbitý (deravy gold-set), inak meríš šum a predavaš ho ako trend.

## GEMMA >> YAR NA PARAFRÁZY — YAR je mŕtva váha vo fúzii (2026-09-27, DOKÁZANÉ na 103)
Na veľkom validovanom v2 gold-sete (103 parafrázových otázok, `mem_eval_gold_v2.json`,
generátor `mem_eval_goldset_v2.py`) vyšlo TVRDO:
      engine            R@1    top-8/103   poznámka
      YAR (súčasný)     0.02      4       = náhoda, na parafrázy SLEPÝ
      BM25 sám          0.40     66
      Gemma sama        0.456    72       (768d, cez gemma_embed_server:8901)
      Gemma+BM25 w=1.5  0.573    88       fúzia bije oba → komplementárne
- **YAR v5 (129D Lorentz, `embed_yar.embed_one`) je na sémantickú parafrázu prakticky
  slepý.** Overené že to NIE je bug konfigurácie: (1) YAR je SYMETRICKÝ — `embed_one` =
  `embed_batch([t])[0]`, žiaden query/doc prefix, korpus aj query idú identicky → prefix
  mismatch VYLÚČENÝ. (2) Set nie je adversariálny — ručná kontrola 8 otázok kde YAR minul
  (>rank 100) ukázala plné prirodzené otázky ("aké poistky do flash skriptu?"). YAR ich
  jednoducho nenájde.
- **Gemma má ASYMETRICKÉ prefixy** (`task: search result | query: ` vs `title: none | text: `,
  `gemma_embed_server.py`) — to je práve to čo YAR nemá a prečo vidí parafrázy. Korpus MUSÍ
  ísť mode=document, query mode=query, inak sa retrieval rozbije (Google model card).
- **Odporúčaný ďalší krok (NEurobené ešte):** nahradiť YAR vetvu vo fúzii `zol_mem`
  Gemmou (w_gemma≈1.5–2.0, bm25=1.0) → recall R@1 0.40→0.58 (+18b), top-8 66→88.
  Gemma engine už existuje (port 8901), korpus sa embeduje ~2 min na GPU (2771 docs).
  POZOR: eval merany na CACHED Gemma npz (`gemma_corpus_v2.npz`/`gemma_gold_v2.npz`),
  produkčná fúzia musí embedovať query za behu cez :8901 (latencia +~50ms/query).
  Pred zapojením premeraj latenciu a rozhodni či Gemma nahradí YAR alebo pribudne k nemu.
- **YAR NEVYHADZUJ z Lorentz kostry** — stále drží hierarchiu/subsumpciu (r→abstrakcia),
  len na PLOCHÝ retrieval je slabý. Ide o výmenu RETRIEVAL vetvy, nie celého YAR.

## OPRAVA GEMMY: kolekcia bola z 70% PRÁZDNA + benchmark klamal (2026-09-29, DOKÁZANÉ)
Focus vedúcka: „prečo sa nepoužíva Gemma? … tak to oprav." Odpoveď mala DVE vrstvy a
obe menili predošlé závery — vrátane mojich vlastných z tejto session.

**1. Gemma SA POUŽÍVA, ale kolekcia bola rozbitá (root cause).** `zol_mem._gemma_query`
(r.365) volá daemon :8901 mode=query + `hs search zol_mem_gemma` a fúzuje. Napojenie
funguje. ALE self-retrieval (embed vlastný text záznamu → hľadaj ho) ukázal **70% aktívnych
záznamov v kolekcii CHÝBALO**, systematicky NOVŠIE ID (medián chýbajúceho 2360 vs 1594).
Dual-write (`mem_store.put` gvec vetva) v istom bode prestal zapisovať.
- **PASCA HNSW-search-topk NEMERIA pokrytie:** `search topk=4000` vrátil len ~400 ID (ANN
  strop) → falošné „88% chýba". SPOĽAHLIVÉ pokrytie = self-retrieval na VZORKE (každá query
  vracia svoje okolie, žiaden strop): 40 náhodných, embed vlastný text, je vlastné ID v top-5?
- **PASCA insert-do-rozbitej-kolekcie KLAME:** `hs.mjs insert` na `zol_mem_gemma` vrátil
  `{"inserted":3371}` rc 0 BEZ chyby, ale count sa nehol a záznamy neboli dohľadateľné ani
  na vlastný vektor. Dôkaz že to je kolekcia a nie kód: ten istý insert #2912 do ČERSTVEJ
  kolekcie `_gemma_probe` → count 3, rank 1. **Poškodená HyperspaceDB kolekcia môže ticho
  prijímať inserty (inserted:N) a zahadzovať ich.** get/stats/MCP get_stats na nej hlásia
  NOT_FOUND, hoci list+search ju vidia = rozladený index/metadata.
- **FIX = drop + recreate + BATCHED backfill.** Gemma vektory sú čistý DERIVÁT
  `mem_index.jsonl` (re-embed kedykoľvek, žiadna strata) → bezpečné dropnúť. `hs delete
  zol_mem_gemma` → `hs create zol_mem_gemma 768 cosine` → backfill. **`gemma_backfill.py`
  (repo) embeduje VŠETKO v JEDNOM HTTP requeste → TimeoutError na 3371 textoch.** Riešenie:
  batched (64/dávka, insert po dávke, retry). Po oprave count 3386=3386, pokrytie 30%→100%.

**2. `mem_eval.py` MERIA OCHUDOBNENÚ FÚZIU — jeho čísla NEODRÁŽAJÚ reálny recall.**
`mem_eval.py` počíta len yar_only/bm25_only/hybrid(yar+bm25) a Gemmu VÔBEC nemeria (r.155
`sem`+`lex`, žiadny gem). Navyše NEMÁ current-state filter ani unified re-scoring
(relevance×recency×importance) čo `cmd_recall` má. Preto dával bm25 0.40 / yar 0.02 —
čísla čo NEZODPOVEDAJÚ realite. **Reálny end-to-end `cmd_recall` na tom istom v2 sete:**
      konfigurácia                    R@1     MRR    top8   found
      bez Gemmy (starý de-facto)      0.728   0.761   82     82
      +Gemma W_GEM=0.8 (stará váha)   0.816   0.835   88     88
      +Gemma W_GEM=1.5 (NOVÝ default) 0.845   0.850   88     88   <- vrchol
      +Gemma W_GEM=2.0               0.835   0.843   88     88
      +Gemma W_GEM=3.0               0.825   0.841   89     89
- **VÝSLEDOK: oprava Gemmy pridala reálnemu recallu +11.7b R@1** (0.728→0.845), found 82→88.
  Stará váha 0.8 bola tunená na POLÁMANÚ (prázdnu) Gemmu → podceněná. Nový default W_GEM=1.5
  (patchnutý v zol_mem.py cmd_recall). Predošlý session-záver „recall je de-facto R@1 0.40,
  YAR mŕtvy" bol ARTEFAKT ochudobneného benchmarku — reálny recall bol vždy ~0.73+.
- **PONČENIE (najdôležitejšie z celej session):** benchmark ktorý nevolá PRODUKČNÚ cestu
  (tu `cmd_recall`) meria fikciu. Než vyhlásiš číslo o recalle, over že meriaš to čo systém
  REÁLNE robí — nie izolovanú vetvu bez fúzie/filtrov. A retrieval pokrytie meraj
  self-retrievalom, nie HNSW topk (má strop). E2E meranie rob IN-PROCESS s memoizáciou
  embedov (nezávisia od váh) — subprocess-per-query re-importuje YAR 400× a visí 30 min.

## DRUHÝ BUG: Gemma bola len RE-RANKER, nie RETRIEVER (2026-09-30, commit e3e6fce)
Po oprave kolekcie fokús vedúcka „načítal len YAR? máme viac než YAR" dotlačil pozrieť fúziu.
- **Root cause:** `cmd_recall` plnil `meta_by_id` LEN z YAR (`res`) + BM25 (`lex`), a
  `fused_score` iteruje `for mid in meta_by_id`. Záznam ktorý našla IBA Gemma (mimo YAR aj
  BM25 fetch poolu) nemal meta → v kandidátskej slučke prepadol (`if not r: continue`).
  Gemma teda vedela len RE-RANKOVAŤ nálezy ostatných, nie prispieť vlastný retrieval —
  a to je jej NAJCENNEJŠIA schopnosť (sémantická parafáza čo BM25 minie).
- **Dôkaz číslom (v2 gold):** 15/103 targetov Gemma chytila do poolu ale fúzia zahodila;
  priemer 19.7 Gemma-unique ID zahodenych/query. Meria sa: pre každú query porovnaj
  `gem_ids - (yar_ids | lex_ids)` a koľko z nich je gold target.
- **Fix:** doplniť gemma-unique ID (mimo YAR+BM25) do `meta_by_id` s plným textom z
  `_graph_index_by_id()` (nie orezaný Gemma-meta text). Solo nálezy dostanu discount
  `GEM_SOLO` (default 0.8) — slabší signal (1 vetva) nesmie s plnou W_GEM prevalcovať
  konsenzus. Env: `ZOL_RECALL_GEMMA_UNIQUE=0` vypne celé, `ZOL_RECALL_GEM_SOLO=1.0` bez discountu.
- **GEM_SOLO sweep:** OFF R@1 0.495/found 74 | 1.0 R@1 0.456/found 82 (plná váha zrazí R@1)
  | 0.8 R@1 0.485/R@5 0.728/MRR 0.587/found 82 (optimum). Čista výhra: found +8, MRR +0.014,
  R@1 -0.010 (1 query = HNSW šum). Discount na solo-vetvové nálezy je všeobecný pattern.
- **METODOLOGICKÁ LEKCIA (tretie ukvapenie za session):** prvé meranie fixu dalo R@1 0.466
  vs „baseline 0.845" → vyzeralo ako KATASTROFA, ale baseline merala INÁ konfig/skript.
  NIKDY neporovnávaj nové číslo s číslom z iného behu/skriptu. Sprav APPLES-TO-APPLES:
  ten istý skript, prepni len jednu vec cez env (ON vs OFF). Rozhodovacie pravidlo naplánuj
  PRED behom (ak R@1≥OFF a found>OFF → commit; inak revert), nech ťa výsledok nezvedie
  racionalizovať. HNSW je approximate → ±0.01 R@1 medzi behmi je šum, nie signál.

## FAIL-HANDLING NA JEDNOM MIESTE — fail-LOUD + self-heal + notify (2026-10-01, commit bc23ea3)
Vedúcko: „nemáme recall na 3 miestach že niektoré môžu ticho fail a niektoré nie? chcel
by som to na jednom mieste." Mal pravdu — fail-handling bol rozsypaný na **5 miestach s 3
politikami:** `embed_one` (YAR query) BEZ ochrany → tvrdý crash celého recallu (diera #1);
YAR/DB search fail-CLOSED; BM25 + Gemma + Opus rerank fail-OPEN **TICHO**. Práve to tiché
Gemma fail-open je prečo Gemma padala týždne neviditeľne (viď dve sekcie vyššie).
- **Riešenie = jeden `degraded` dict + jedno rozhodovacie miesto.** Každá vetva v `cmd_recall`
  už len zapíše zlyhanie do `degraded[lens]=dôvod`. Na konci `recall_health.report()`
  (nový modul `toolkit/recall_health.py`) rozhodne čo s tým. `_gemma_query` zmenené aby
  vracalo `(hits, err)` namiesto tichého `[]`.
- **Politika = fail-LOUD, NIE fail-closed-per-vetva.** Vedúcko najprv chcel „fail-closed keď
  padne ktorákoľvek", ale to by z 1 mŕtvej vetvy (padne len Gemma, YAR+BM25 bežia) spravilo
  TOTÁLNY výpadok pamäte — pamäť krehkejšia, nie spoľahlivejšia. Pomenované nahlas, postavené
  ako fail-LOUD: padne JEDNA vetva → recall degraduje VIDITEĽNE (LLM to musí spomenúť) +
  notify + self-heal, beží na zvyšných. Prázdno (`backend: DOWN`) LEN keď padnú VŠETKY tri
  retrieval vetvy (`total_outage = not res and not lex and not gem`).
- **Tri efekty, všetko cez EXISTUJÚCU infra (nič duplicitné):** (1) LLM informovanie —
  session-start recall dostane `⚠️ RECALL DEGRADOVANÝ (povedz to vedúckovi)` ako prefix cez
  `format_recall_hits`; (2) notify — `zolander_notify.py` (inbox+desktop banner+push); (3)
  self-heal — `launchctl kickstart -k gui/<uid>/<label>` daemona (`pl.zolander.hyperspace` pre
  DB, `pl.zolander.gemmaembed` pre Gemma). YAR embed (v procese) a BM25 (súbor) sa restartnúť
  nedajú → len notify.
- **Dve poistky aby liek nebol horší než choroba:** (a) THROTTLE cez `state/recall_health_ledger.json`
  — notify 1×/30min, heal 1×/5min per vetva (inak Gemma-down spamuje banner + bije launchd pri
  KAŽDOM recalle); (b) VÝSTUPNÝ KONTRAKT — dict wrapper s `degraded` ide LEN pre
  `source=session_hook` (jediná LLM-facing cesta, `format_recall_hits` je dict-tolerantný);
  strojoví konzumenti (patterns/dream/diag) dostanú HOLÝ LIST ako vždy, inak sa rozbijú
  (iterujú výstup priamo `for h in hits`).
- **Dôkaz naostro (Gemma daemon down, zlý port 59999):** session_hook → dict s „RECALL
  DEGRADOVANY — EmbeddingGemma 3. lens"; patterns → holý list; recall našiel 5 spomienok
  (bežal na YAR+BM25); notify by sa vystrelil. Recall testy (current_state/telemetry/graph_expand)
  zelené. Celá health vrstva fail-open (chyba v nej nezhodí recall).
- **PONČENIE (prenosné):** keď máš N vetiev s rôznym fail správaním, NEzjednocuj ich na
  „všetky fail-closed" (najkrehkejšia vetva potom zhodí celok) ani „všetky ticho fail-open"
  (tiché zlyhanie je neviditeľný dlh). Správny vzor = zbierať zlyhania do JEDNÉHO zoznamu,
  JEDNO miesto rozhodne, degradácia je VIDITEĽNÁ (fail-LOUD) a prázdno len pri úplnom výpadku.
  Self-heal daj na existujúce launchd labely, notify na existujúci kanál — nestavaj 7. nástroj.
