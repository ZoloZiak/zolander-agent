# OPENCODE_PORT.md — Zolander na opencode, fáza 1 + fáza 2 (dual pamat)

> Zolander pôvodne bezal na [Hermes Agent](https://hermes-agent.nousresearch.com) (macOS).
> Toto je jeho port na **opencode** (Windows) s modelom **`opencode/glm-5.3-flash-free`**
> (zadarmo v opencode; mimo opencode je endpoint `opencode.ai/inference/...` rate-limitovany 429, overené 2026-10-26).
> Stejná poctivosť ako v README: rozdelenie co BEZI a co je ROADMAP. Bez green-checku sa
> tvrdenie nedostane do tejto sekcie.

## Co bezi dnes (green-checks)

- **Persona ako opencode agent.** `.opencode/agents/zolander.md` (mode: primary,
  model `opencode/glm-5.3-flash-free`) + `.opencode/opencode.json`
  (`default_agent: zolander`, permissions).
  *Zdroj:* harness skill-list ukazuje skill `zolander` — discovery funguje.
- **Recall-first (port hermes `pre_llm_call` hook).** Zastarané — superseded
  dual recallom nižšie (fáza 2). Pôvodný single-shot injekt bol vymenený
  za `[Zolander DUAL RECALL — A/B test]` blok.
- **Hard foundation do systému (anti-drift).** Ten istý plugin — session hook
  `context` pushuje do systemového kontextu krátký F11/sandbox/honesty blok
  (port hermes myšlienky "data injection belongs in hooks", nie v prose).
- **Mechanická anti-halucinácia/anti-sycophancy brána.** Bez zmeny, pôvodný
  `toolkit/zol_guard.py` (stdlib, bez LLM) pracuje aj na Windows.
  *Green-check:* `python toolkit/zol_guard.py` vypise rezimy (overené rucne,
  exit 2 bez argmentu a bez LLM); `verify-*` volania idú na skutocné subory.
- **Double-take brána (jadro).** Nový mode `echo '{"problem":...}' | python
  toolkit/lens.py gate-classify` — čisto deterministický klasifikátor bez LLM.
  Port-rozdiel: `lift` robí agent sám (vlastná revizia), NIE Opus cez hermes.
  *Green-check:* serious otázka skore 3 → `double_take: true`; trivialná skore 0
  → `false` (overené 2026-10-26 na Windowse).
- **Light pamat L0.** `toolkit/mem_light.py` (nový, stdlib) →
  `state/zol_memory.jsonl`; lexikalny recall (keyword prekryv + recencia),
  schema kompatibilná so zol_mem (kind/layer/salience/confidence).
  *Green-check:* `python toolkit/mem_light.py remember --text "..."` potom
  `... recall --query "..."` — hit s score (overené 2026-10-26: score 4.95).
- **Hyperbolská pamat L2 jadro (HyperspaceDB v4.0.1, server-side embedding).**
  Server postavený v klonu `/home/zolo/hyperspace-db-401` vo WSL Ubuntu (7m 47s
  release build), kolekcia `zol_mem` (lorentz, 129D), embedding YARlabs
  `v5_Embedding_0.5B` (`v5_Embedding.onnx`) beží V SERVERI — Python strana má
  len grpcio (žiaden torch). RPC: `InsertText`/`SearchText` + plaintext
  prenesený v metadannoch (server po embednutí samotný text zahodí — overené
  v server.rs, fix v `zol_mem_text.py`). Klient `toolkit/zol_mem_text.py`
  (venv `~\.venv-zolander`), RPC chyby sa premenia na poctivý `ok:false`
  (SDK inak printne "RPC Error" a vráti falsy výsledok).
  *Green-check:* `zol_mem_text.py health` → `{"status":"ONLINE"}` (HTTP 50050;
  gRPC NOT_FOUND na neexistujúcej kolekcii pred initom je poctivé znamenie);
  `zol_mem_text.py init` → ok:true; remember → id, recall → hit s `distance`
  (lorentz d 0.713) a plným plaintextom (overené 2026-10-26).
  Štart serveru pri logone: Startup-folder
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\zolander-hyperspace.vbs`
  (skryté `wsl.exe` okno, beží na pozadí). Pozor: to nie je Windows služba —
  len autostart pri logone; neuhol snáďno-WSL-šutdown ho zabije (watchdog
  ho restartne, pozri Scheduled Tasks nižšie).
- **DUAL RECALL A/B (fáza 2 injekt).** Plugin session hook `prompt` vstrieka
  `[Zolander DUAL RECALL — A/B test]` blok: **RECALL A** = lexikálna L0
  (`mem_light.py`, keyword prekryv + recencia), **RECALL B** = semantická
  lorentz (`zol_mem_text.py` → HyperspaceDB server-side embedding). Oba recall-
  y bežia nad ROVNAKÝM query textom (user správa), výsledky sú jasne oddelené
  a každý hit nesie skóre/kind/layer/confidence. A ked citaš zapamätanú vec,
  pravidlo v systéme žiada označiť odkial (A/B). Ak je B nedostupný (server
  nebeží), blok hovorí `NEDOSTUPNY (server nedostupny…)` — nepredstiera
  výsledky. `ZOLANDER_RECALL_EVERY=1` = recall na každú správu (default raz
  za session).
  *Zdroj:* `toolkit/zol_recall_dual.mjs` (čistá logika, zdielaná pluginom
  a testom), `toolkit/zol_remember_dual.py` (zápis do OBOCH pamätí naraz).
  *Green-check:* `node toolkit/zol_test_dual.mjs "<query>"` — renderuje presný
  injekt a validuje formát; overené 2026-10-26 (A: hit s 13.283, B: hit
  lorentz d 0.713, oba s plným textom). Live recall cez server embedding
  overené 2026-10-26.
- **A2A Ed25519 podpis pamati (integrita + identita zápisov).** Orchestrátor
  `zol_remember_dual.py` podpíše každý zápis JEDNým podpisom pred zápisom do
  oboch pamätí (kanonické telo `json.dumps({text,kind,layer,confidence},
  sort_keys, separators=(",",":"))`), podpis nesú oba záznamy (A: polia
  `sig`/`sig_from_fp`/`sig_ts` v JSONL; B: kľúče v metadannoch gRPC bodu).
  Identita: `identity/zolander_ed25519.key`, fingerprint `9ae2fbc6…`.
  *Green-check:* `python toolkit/zol_remember_dual.py verify --limit 5` →
  overí podpisy v OBOCH pamätiach (overené 2026-10-26: 2 overené podpísané,
  4 staré legacy `unsigned` — zápisy pred wiringom, poctivo odlíšené, 0 zlyhale).
  Tamper test: zmena textu po podpise → `PODPIS NESEDI` (overené 2026-10-26).
  *UTF-8 green-check (2026-10-26, 23:18):* zápis diakritiky (ť/ž/ľ/ň/ô/č/š)
  cez `--file` (UTF-8 payload súbor + `PYTHONUTF8=1` env pre detské procesy,
  nie stdin pipe — PowerShell 5.1 posiela do stdin ASCII) sa uložil
  BAJTOVO IDENTICKY v A aj B (byte-compare true/true). Pozor: mojibake vo
  výpise konzoly je len zobrazovací artefakt, nie dáta.
- **L1 + L2 ascend (L0 → L1 → L2 koncepty).** `toolkit/zol_ascend.py`:
  server-side `FindSemanticClusters` (HNSW graf; hrany HIERARCHY) → rule-based
  koncepty client-side → dual zápis (A2A podpis, members/members_hash,
  dedup). DVA passes: L0→L1 a L1→L2 (ten sa robehne, keď je dosť L1 hmoty —
  dnes 0 nových, poctivo v reporte).
  *Green-check (2026-10-26/27):* L1: 4 clustery z 11 L0 → 4 koncepty
  (B 23–26), druhý beh `skipped_dedup` všetky; L2 pass live (0 clusters —
  málo L1 hmoty, mechanizmus spustený); `verify` 12/12 podpisov OK.
- **B-strana decay (zol_decay_b.py).** Salience * 0.95 aj na lorentz pamäti
  cez `UpdatePayload` RPC (SDK má bug: číta `resp.code`, ale proto má
  `StatusResponse{status}` — obídené raw stubom, overené status reťazec).
  Celá metadata mapy sa posielajú (server ju nahrádzza celú) — plaintext
  prežije (overené). Dream ho volá po A decay.
  *Green-check (2026-10-27):* dry → 17 kandidátov, execute → 17 changed,
  0 errors, text zachovaný v metadate.
- **Forget politika (zol_forget.py).** DEFAULT DRY: vypíše návrhy
  (L0, salience < 0.25) — nič nemaže. `--execute --confirm YES` maže
  (B delete RPC + A jsonl rewrite) a ZAPOČÍ A2A podpísaný audit
  (`source=forget-audit`) do oboch pamätí. Bez `--confirm YES` odmietne.
  *Green-check (2026-10-27):* sacrificial záznam (conf 0.05) → dry našiel
  1 kandidáta A+B → execute → A+B zmazané, audit podpísaný redočijaný,
  ďalší dry → 0 kandidátov, `verify` audit record OK.
- **Mechanické bezpečie.** `permissions` v `.opencode/opencode.json`:
  tvrdo DENY: `git push --force*`, `*rm -rf *`, `*del /s *`, `*format *`.
  Poznámka poctivosti (2026-10-26/27 nocnú session): opencode si počas
  práce užívateľskými „always allow“ klikmi Moje prepísal shell/subagent/
  external_directory na allow — config odrazy reálnu voľbu vedúca, nie
  zlyhanie mechanizmu. Ďalšie hard deny tripky zostávajú.
- **Daemony portované (loop/watchdog/dream) + Scheduled Tasks.** Port hermes
  launchd cronov na Windows (PowerShell `Register-ScheduledTask`, user-level;
  `schtasks` CLI je v tomto prostredí Access denied — obídené):
  - **"Zolander Loop"** (každých 15 min) → `toolkit/zol_loop_port.py`:
    integrity check + heartbeat `state/heartbeat.txt` + sken nezacomitovaných
    zmien repa + `logs/loop.log`. Cisto stdlib, bez LLM.
  - **"Zolander Watchdog"** (každých 15 min) → `toolkit/zol_watchdog_port.py`:
    health `zol_mem_text.py`; ak server padol, Popen-restartuje WSL server
    (log `logs/watchdog.log`). Nemaže nič — len restart.
  - **"Zolander Dream"** (denne 03:00) → `toolkit/zol_dream_port.py`:
    decay ×0.95 salience na A záznamoch, rule-based konsolidácia dňa do L1
    (dual zapis, A2A podpis), ranný brief `denniky/brief_<dátum>.md`. Nič
    NEmaze — forget len navrhuje. Honesty: konsolidácia je rule-based destilát,
    NIE LLM (port nemá MCP consolidate engine).
  *Green-check:* jednorázové behy všetkých troch overené 2026-10-26 (loop:
  heartbeat+log, dirty=6; watchdog: "OK server zivy, A mem ok"; dream: decay
  5 záznamov, brief `brief_2026-10-26.md`, poctivo "dnes žiadne episodic").
  Tick scheduled tasku overené reálne: "Zolander Loop" loop.log záznam 22:48:54
  (nie manuálne spustenie) + "Zolander Watchdog" watchdog.log tick 22:54:03
  (idle health OK). Dream task `State: Ready` — prvý odpal o 03:00,
  overím ráno (plánované ticky potrebujú tiež reálny dôkaz, nie len registráciu).

## Roadmap (NIE je implementované — o tom to celé nie je)

1. **L3 vrstva + LLM destilát konceptov.** L1/L2 BEŽÍ (ascend). Ostáva:
   L3 (ascend nad L2), konsolidácia rule-based → LLM (teraz keyword
   heuristika), forget pre L1/L2 koncepty (teraz ien L0 — koncepty smie
   mazať len ruka veduca).
2. **Cron daemony — zvyšok.** Loop/watchdog/dream portované + Scheduled Tasks
   (pozri "čo beží"). Ostáva: `notify` (notifikácie),
   LLM konsolidácia v drame (teraz rule-based), live overenie plánovaných
   tickov Watchdogu/Dreamu po prvom odpale.
3. **MoA cross-model review** (opt-in analóg `ZOL_VERIFY_MOA` z hook_verify).
4. **A2A peer vrstva (guestbook/inbox).** PODPIS pamati JE napojený (pozri
   vyššie); ostáva peer most (known_peers, spravy od iných agentov) —
   `toolkit/a2a.py` ho má, port nie je pripojený k peerom.
5. **STT (slovenský Whisper), Matrix/WhatsApp gateway, Palantir, macOS banner** —
   neportované; väčšina závisí na prostredie (korporát/macOS), nie na porte.

## Model poctivost (overené 2026-10-26)

- `opencode/glm-5.3-flash-free` — v opencode zadarmo (čísla: input/output/cache 0).
- Priame volanie `https://opencode.ai/inference/openai/v1/chat/completions`
  z externého klienta bez kľúča: funguje po limit (`429 FreeUsageLimitError`,
  "Free models work in OpenCode"). Ked teda beží niečo mimo opencode, musí to
  byt platena cesta (OpenCode Go subscription / OpenRouter / klic) alebo sa cakat na reset.
- Variants: low/high/max (reasoning effort) — default je bez variantu.

## Rýchly test po inštalácii

```
python toolkit/mem_light.py recall --query "port"   # pamat: {"ok": true, hits}
python toolkit/zol_guard.py                          # vypise rezimy + exit 2
```
Opencode v tomto repu: otvor session s agentom `zolander` (`/agents` alebo
default) — prva sprava dostane `[Zolander auto-recall...]` blok.
