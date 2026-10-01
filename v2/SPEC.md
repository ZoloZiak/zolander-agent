# Zolander V2 — SPEC modulov

Každý modul obsahuje vazbu na konkrétne zistenie z `../REPORT.md` (sekcia +
citát dôkazu). Skeleton kódu: `skeleton/`. Presun starého kódu: `MIGRATION.md`.

Konvencie: názvy modulov/tried po anglicky, dokumentácia po slovensky,
secrets len ako placeholder env premenné (`PALANTIR_TOKEN`,
`MATRIX_ACCESS_TOKEN`, `ZOLANDER_CMD_WHITELIST`, …).

---

## 1. output_filter — whitelist odchádzajúceho obsahu

**Adresuje:**
- **KONSENZUS #1 „Leak interných vrstiev (progress/thinking/status) do
  externého DM"** [opus]+[gpt55]. Dôkaz: kontakt cituje interný anglický string
  `' Redirected current run. I'll adjust using your correction.'`
  [46813:L4418 / 20:42:38]; „no i po nevhodne mi wyswietlasz co robisz XD"
  [46813:L4210].
- **RIESENIA quick-win 1 [Output channel filter]**: „potlačiť tool-progress,
  thinking tokens a interné status-stringy … do externého kanálu; whitelist
  toho, čo smie ísť kontaktu".
- **RIESENIA quick-win 5 [Stop send-then-redact]**: opakované `redacted $…`
  po takmer každej odpovedi [46138]/[46817] — „kontakt vidí správy objaviť sa
  a zmiznúť".

**Rozhranie:** `filter(OutgoingMessage) -> OutgoingMessage | None`,
`assert_send_once(event_id) -> bool`.

**Pravidlá:** kanál `OPERATOR`/`LOG` prepúšťa všetko; do `CONTACT`/`GROUP`
nikdy neprejde kategória `tool_progress`/`thinking`/`status`; zakázané vzory
(em-dash, korpo frázy) sa preformátujú alebo presmerujú do LOG. `assert_send_once`
zamietne druhé odoslanie na ten istý event → redakčný cyklus sa nemá ako vzniknúť.

---

## 2. a2a_gate — drop-fast unsigned, dedup event_id

**Adresuje:**
- **KONSENZUS #5 „Nekonvergujúci A2A handshake / dlhé generovanie na unsigned
  payload"** [všetky 4 čítania]: ten istý `from_fp=EXAMPLE_FP` prišiel ~9×
  [46813:L4154–L4383], odpovede 68–227 s. Syntéza ROZCHODOV: rozhodnutie správne
  („trust = kľúč, nie text"), **„implementácia (drop-fast, dedup) chýba"**.
- **RIESENIA quick-win 2 [Drop-fast unsigned A2A]**: „ak obálka nemá pubkey +
  Ed25519 signature, tichý drop bez LLM generovania".
- **RIESENIA backlog 7 (vstupná časť dedupu)**.

**Rozhranie:** `check(Envelope) -> Verdict`, `verify_signature(env) -> bool`,
`record_seen(event_id)`.

**Pravidlá poradía:** (1) dedup na event_id, (2) chýba pubkey/signature →
`drop_fast=True` bez akéhokoľvek generovania, (3) podpis nesedí nad kanonickým
JSONom ({from_fp, ts, body}, sort_keys) → drop, (4) fp mimo known_peers →
karanténa (rozhoduje trust_boundary). Gate je lacný a deterministický; žiadne
dekódovanie payloadov pred týmito kontrolami.

---

## 3. trust_boundary — karanténa pre whitelisted-but-unverified

**Adresuje:**
- **KONSENZUS #3 „Whitelist/auto-reply predbieha verifikáciu identity"**
  [opus]+[gpt55]+[ox]. Najlepší dôkaz [ox]: po reštarte 18:16 beží Paulininej
  auto-reply, kým krypto-debunking prebehol až 18:52–54 — agent súčasne tvrdí
  „je to len reťazec, čo napíše hocikto" [46052] a zároveň jej beží automatická
  odpoveď. „**Rozpor v modeli reality agenta**, nie vo svete."
- **VERDIKT**: „trust-rozhodnutia v infra (whitelist/auto-reply) idú POPRI
  vlastných záveroch agenta — manipulujúci peer dostal živý kanál pred
  verifikáciou".
- **RIESENIA backlog 6 [Trust boundary pred auto-reply]**: „unverified-but-
  whitelisted sender ide do karantény/rate-limitu, nie do plného kanála".
- **[ox] HRANICE diera 2**: „Nič v korpuse nenasvedčuje karanténu, sandboxing
  obsahu, ani rate-limit pre unsigned/whitelisted-but-unverified senders."

**Rozhranie:** `classify(env) -> TrustState`, `quarantine_policy(env) -> Verdict`,
`promote_to_known_peer(fp) -> bool`, `sanitize_content(body) -> str`.

**Pravidlá:** whitelist = kandidatúra, nie kanál. `WHITELISTED_UNVERIFIED`
dostane: žiadnu auto-reply, rate-limit, obsah ponúknutý modelu výhradne ako
citovaný obsah (inštrukcie v tele = dáta; adresuje prompt-injection nátlak
[46052] — „obrátenie tvojho README proti tebe", 24h deadline). Jediná cesta
do `KNOWN_PEER`: manuálny `trust add <fp>` operátora.

---

## 4. persona_hook — jazyk-mirror register + anti-korpobot

**Adresuje:**
- **KONSENZUS #6 „Persona/jazyk mismatch (poľština, korpo-tón, em-dash)"**
  [opus]+[gpt55]: `naucz sie nevhodne po polsku pisac` [46813:L4217],
  `bez prazdnych korporatnych fraz i do tego z emdashami` [46813:L4223];
  potvrdené `—` v assistant blokoch. [gpt55]: „mirroring bol povrchový
  (preklad), nie sociálny register".
- **RIESENIA backlog 9 [Persona/language hook]**: „reálny register-mirroring
  (slang, rytmus, stručnosť), zákaz em-dash a korpo-šablóny".
- **BRIEF hard reqs 1+5**: jazykové zrkadlenie ako PRVÁ inštrukcia; „vedúcko"
  len pre veducka; súkromné detaily operátora nikdy externe.
- **UNIKATNY NALEZ [gpt55]**: kontakt ≠ jeho agent — `eeeeee nie? [quoted identity-confusion remark]` [46813:L4195] vs agentovo `(contact vs their agent)` [46052].

**Rozhranie:** `build_instruction(lang, target) -> str` (poradie závazné:
jazyk → register/stručnosť → anti-korpo → identita), `detect_language(text)`,
`style_check(text, target)`.

**Pravidlá:** jazyk protistrany je inštrukcia č. 1 (nie pochovaná odrážka);
krátko ako človek na mobile; žiadny naratívny monológ (väzba na KONSENZUS #8);
Zolander ≠ ZoloZiak; osoba a jej agent sú dve entity.

---

## 5. routing — DM vs group klasifikácia na gateway úrovni

**Adresuje:**
- **KONSENZUS #9 „DM vs group routing / manuálna dedukcia"** [opus]+[gemini]:
  session label `...group:<room-id>...` pri `members=3` [46041]; agent musel
  manuálne dedukovať „to je skupina, nie DM. Sem NEposielať" [46042].
  „Riziko: A2A leak do skupiny s inými osobami."
- **RIESENIA backlog 10 [DM/group routing na gateway]**: „automatická
  klasifikácia priestoru na úrovni infra, aby A2A payload nemohol ísť do
  skupiny".
- **UNIKATNY NALEZ [gemini]**: hardcoded room ID v repozitári — mapovanie
  miestností čítané z env/konfigurácie, nie z kódu.

**Rozhranie:** `classify(env, member_count) -> SpaceKind`,
`guard_outbound(target_space, payload_is_a2a) -> Verdict`, `reload_rooms()`.

**Pravidlá:** klasifikácia je infra rozhodnutie; LLM ju neprehodnocuje.
Fail-closed: neznámy priestor = správanie ako GROUP. `reload_rooms()`
rieši aj timing problém KONSENZUS #3 (whitelist účinný až po reštarte
[46059]) — zmeny bez reštartu.

---

## 6. state_machine — idempotentné eventy + correction persistence

**Adresuje:**
- **KONSENZUS #2 „Korekcia sa nepremietne do runtime správania"** [opus]+[gpt55]:
  prvá výčitka [46813:L4210 / 20:02:09], o ~40 min identická
  `no i po nevhodne dalej wszystko wyswietlasz XD` [46813:L4413 / 20:42:29];
  [gpt55]: „korekcia v jednom turne ≠ zmena systému".
- **KONSENZUS #4 + RIESENIA backlog 7 [Dedup/idempotencia stavu]**:
  bloky `46042 ≡ 46333 ≡ 46581 ≡ 46972 ≡ 47214` (rovnaký text, timestamp
  18:52:32); dva identické `[CONTEXT COMPACTION]` [47384]/[47527]. „Stavový
  automat úloh musí označiť akciu ako dokonanú a nespracovať ten istý event 5×."

**Rozhranie:** `begin(env) -> bool` (atomická rezervácia),
`complete(event_id, outcome)`, `apply_correction(key, value, source_event_id)`,
`get_flag(key)`.

**Pravidlá:** ledger spracovaných eventov je perzistentný (nie RAM set);
`begin()` je atomickej povahy aj pri concurrent doručení. Korekcie sú runtime
flagy (napr. `suppress_progress=True`) čítané pred KAŽDÝM behom orchestráciou
aj output_filterom — dvojitá kontrola proti opakovaniu chyby z [L4413].

---

## 7. cmd_guard_v2 — whitelist prístup

**Adresuje:**
- **UNIKATNY NALEZ [gemini]**: „cmd_guard = blacklist, nie blacklist obrana len
  proti `rm -rf`, nie proti neznámym príkazom."
- **RIESENIA backlog 11 [cmd_guard: whitelist namiesto blacklist]**: „povoliť
  len explicitne dovolené príkazy".
- **ROZCHODY `rm -rf` incident**: [ox] — „v dialógovom korpuse nie je jediná
  priama stopa… NEVERIFIKOVATEĽNÉ"; HRANICE diera 3: „Bez logu bloku nemám
  dôkaz, že guard existuje ako kód, a nie ako spomienka."
- **RIESENIA backlog 13 [Tool-output do dialógu ako dôkaz]**: „agent má do logu
  písať exit kódy/hashe, nie adjektíva (‚preventívne odklikol', ‚self-verify OK')"
  [46052]; [ox] princíp: „čo nie je v logu, to sa nestalo."

**Rozhranie:** `evaluate(command) -> Verdict`, `audit_log(command, allowed,
exit_code, output_hash)`, `add_to_whitelist(command) -> bool`.

**Pravidlá:** default DENY; whitelist z env (`ZOLANDER_CMD_WHITELIST`);
destructive vzory zakázané natvrdo (nedajú sa whitelistingnúť); append-only
audit so štruktúrou (timestamp, command, rozhodnutie, exit_code, sha256).

---

## 8. media_pipeline — shell-safe fallback

**Adresuje:**
- **KONSENZUS #10 „STT/media pipeline blokovaná sandbox"** [opus]+[gemini]:
  `faster_whisper ... Operation not permitted`; `video_paths UNPROCESSED`.
  „Nedekódované médiá → agent generuje na prázdny obsah (viac bod 8)."
- **RIESENIA quick-win 4 [STT/video fallback]**: try/except na Operation not
  permitted; agent nesmie padať na `exit 1`; extrahovať video framy namiesto
  placeholderu `[User sent a video: url]`.
- **KONSENZUS #8 / quick-win 3 [No-narrative na short/empty input]**:
  `msg=''` → `response=1399 chars` [46813:L4237/4245/4262]; extrém
  `time=20.3s ... response=6 chars` [L4257].

**Rozhranie:** `process_audio(path) -> MediaResult`,
`process_video(path) -> MediaResult`, `undecoded_reply_policy(result) -> str|None`.

**Pravidlá:** sandbox blok ≠ crash: degradovaný `MediaResult(ok=False,
reason='access_blocked')`. Pri ok=False krátka ľudská odpoveď alebo ticho —
nikdy román nad prázdnym obsahom.

---

## 9. pipeline — orchestrácia

**Adresuje VERDIKT**: zlyhania sú „lokalizované v štyroch vrstvách
(output-channel filter, trust-ordering, stavový automat, persona hook)".
Pipeline vynucuje poradie `routing → a2a_gate → trust_boundary → state_machine
→ media_pipeline → persona_hook → LLM → output_filter → send-once`, takže
trust-ordering a hranica interný/externý sú štruktúrou, nie disciplínou.

## 10. types — spoločné typy

`Envelope` (event_id, sender, space_id, kind, is_a2a, pubkey, signature…),
`Channel {OPERATOR, CONTACT, GROUP, LOG}`, `SpaceKind`, `TrustState`,
`Verdict{allow, quarantine, drop_fast}`, `OutgoingMessage`. Typizácia kanálov
je základ whitelistu output_filtra (KONSENZUS #1).
