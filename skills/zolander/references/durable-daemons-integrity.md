# Zolander durable daemons + integrity manifest

## Prehľad — dvaja bežiaci launchd agenti (overené naostro)
launchd = natívny macOS spôsob, prežije zatvorenie terminálu AJ reštart Macu.
Plisty v `~/Library/LaunchAgents/`:

- **pl.zolander.loop** — `StartInterval 1200` (každých 20 min), `RunAtLoad true`,
  `ProcessType Background`. Spúšťa `/usr/bin/python3 toolkit/zolander_loop.py`
  (sys python3, len stdlib — žiaden venv). Jeden tick (F3):
    1. integrity check (fail-closed: ak zlyhá → zaloguj a KONIEC, nič ďalšie)
    2. heartbeat → `state/heartbeat.txt` (json: ts, pid, epoch)
    3. sken dovolených git projektov (zolo2.0, turiec-pod-lupou) na nezacomitované zmeny
    4. tick riadok do `logs/loop.log`
  ZÁMERNE bez LLM (lacné, overiteľné, deterministické). „Pozoruje", nekoná prácu.
- **pl.zolander.dream** — `StartCalendarInterval` Hour 3 Minute 0, `RunAtLoad false`.
  Spúšťa `zolander_dream.py` (F4 „sen") — LLM konsolidácia epizód do L1 destilátov +
  ascend abstrakčný rebrík. Toto JE LLM-tick, fresh proces.

Overenie stavu: `launchctl list | grep zolander` (stĺpec: `-` PID znamená momentálne
nebeží medzi tickmi, číslo = posledný exit status). `cat state/heartbeat.txt` musí mať
čerstvý ts. `logs/launchd.err.log` prázdny = OK.

## PASCA: integrity FAIL-CLOSED zabíja loop po každom edite SKILL.md
`toolkit/integrity.py` — SHA-256 manifest identity. FILES = { skill: ~/.hermes/skills/
note-taking/zolander/SKILL.md, pub: identity/zolander_ed25519.pub, fingerprint:
identity/fingerprint.txt }. Manifest: `identity/integrity.sha256`. Privátny kľúč sa
NEhashuje (mení sa chmod), len sa kontroluje existencia.

Režimy: `integrity.py write` (zapíš nové hashe), `integrity.py check` (exit 0 OK /
1 mismatch, vypíše KTORÝ súbor nesedí). `zolander_loop.py` volá check ako fail-closed
bránu: pri mismatch (aj pri chýbajúcom skripte/manifeste) tick končí BEZ heartbeatu.

REÁLNY INCIDENT (2026-08-05 → 08-08, ~2,5 dňa): v minulej session sme pridali do
SKILL.md double-take bránu + green-check konvenciu, ale NIKTO nespustil `integrity.py
write`. Loop od 07:39 každých 20 min logoval „INTEGRITY FAIL — identita zmenena! tick
prerušený", heartbeat zamrznutý. `integrity.py check` ukázal `MISMATCH skill` (OK pub,
OK fingerprint) — čiže náš vlastný legitímny edit, nie útok. Oprava = 1 príkaz:
`/usr/bin/python3 ~/projects/zolander/toolkit/integrity.py write`, potom ručný `zolander_loop.py`
(exit 0 + heartbeat sa pohol) na overenie. NEČAKAJ 20 min na launchd — over ručne.

PRAVIDLO: po AKEJKOĽVEK zmene SKILL.md alebo identity súborov VŽDY hneď re-baseline
manifestu. Zvlášť zákerné je, že aj samotný curator/skill-update patch SKILL.md rozbije
loop — takže po každom patchi tejto skilly treba `integrity.py write`.

## PASCA: dedup deadlock — iniciatíva umlčaná 24 dní jedným nevybaveným návrhom
REÁLNY INCIDENT (2026-09-04 → 09-28, 24 dní): initiative daemon tikal á 30 min, generoval
návrhy, ale VŠETKY zožral `DEDUP: uz existuje otvoreny navrh — nespamovat`. Vedúcko preto
24 dní nedostal ani jeden `🔧 Návrh #N`. Príčina: `_pending_open_for` je per-projekt dedup
ktorý blokuje KAŽDÝ ďalší návrh k projektu s otvoreným `status:pending`. Dva pending nikdy
nikto nezavrel (pid=14 zolo2.0, pid=15 turiec) → keďže turiec bol jediná téma, neprešlo NIČ.
Deadlock: čaká na „zrob N", ktoré nepríde, lebo tie správy vedúcko nikdy nevidel.

OPRAVA (nasadená 2026-09-28): `PENDING_EXPIRE_DAYS=14` + helper `_pending_is_active(rec)` —
pending starší než 14 dní prestane blokovať. Fail-open: neparsovateľný ts → čerstvý (radšej
blokuj než spamuj). Zapojené do OBOCH dedup vetiev (`_title_dup_in_pending`,
`_pending_open_for`). Env override `ZOL_INIT_PENDING_EXPIRE_DAYS`.

PRAVIDLO — diagnostika daemona po VÝSTUPE, nie po tikoch: „proces tiká" ≠ „vedúckovi niečo
prišlo". Vždy meraj čo REÁLNE odišlo cez kanál (grep `ODOSLANE`/`PUSH ok` v logu + počet a
dátum poslednej), nie počet tickov. A pozor: aj `ODOSLANE`/`PUSH ok rc=0` je len self-report
push príkazu — NEdokazuje doručenie na mobil, to potvrdí len vedúcko.

PRAVIDLO — každý stavový zámok čakajúci na ľudskú akciu potrebuje auto-expire, inak jeden
nevybavený záznam umlčí celý kanál navždy.

## PASCA: push kanál je krehký (rc=1 / TimeoutExpired) — daj retry
Ranné briefy (zolander_notify.py `try_push`) 2026-09-25→27 hlásili `PUSH zlyhal rc=1` a
`detect_target TimeoutExpired`. Prechodné: bridge sa práve reštartoval / `hermes send
--list` presiahol timeout. OPRAVA: 3 pokusy s backoffom 3s/6s v `try_push` (notify.py) aj
`_send_whatsapp` (initiative.py). Env: `ZOL_NOTIFY_PUSH_RETRIES` / `ZOL_INIT_PUSH_RETRIES`.
POZOR: notify.py nemal `import time` — retry by hodil NameError; doplnené. Po edite pusti
`py_compile` OBOCH súborov. Overenie kanála: `hermes send --list --json` (živý = vráti
whatsapp id typu `...@lid`); `pgrep -fl node` musí ukázať `bridge.js --port 3111`.

## POSTAVENÝ 3. agent — forget_audit.py (pracovný LLM-tick, prvá reálna úloha)
REÁLNE NASADENÉ 2026-09-29 (vedúcko: „dáme loopu reálnu prácu"). Prvý Zolander agent
ktorý KONÁ kognitívnu prácu (nie len pozoruje ako loop / nekonsoliduje ako dream).

PROBLÉM: `cmd_decay` (zol_mem.py) je MECHANICKÝ — hodí do forget fronty každý episodic
záznam starší než prah + pod salience prahom, BEZ posúdenia obsahu. Fronta len rástla
(201→334) a nikto ju nečítal. „implementoval gradient oblohu" ležalo v tej istej kope ako
„__USER__ potrebuje rituál štartu" a „osobná poznámka X".

RIEŠENIE: `toolkit/forget_audit.py` = LLM vrstva NAD mechanickým výstupom. Pre každého
kandidáta (forget_state dormant/retired_candidate) dá Opus verdikt forget/keep/promote
(+promote_kind semantic/procedural/identity). BEZPEČNOSŤ: NEMAŽE a NEMENÍ pamäť — len
píše verdikty na schválenie do `work/forget_audit/verdicts.jsonl`. Aplikácia = za „zrob N".
PRVÝ BEH (334 kand.): 107 forget, 159 keep, 68 promote (26 identity, 29 semantic, 13 proc).
= 68 trvalých faktov o vedúckovi čo decay ticho drvil na nulu.

DIZAJN (durable-unattended-batch-jobs vzor, overéí naostro):
- progress.json = zdroj pravdy (done_ids), idempotentný resume (ŠTRUKTURÁLNY check: id už
  má verdikt), atomický zápis (tmp+os.replace) po KAŽDOM batchi (crash-safe).
- LLM dostane {id,text}, vracia LEN {id,verdikt,dovod,promote_kind} — text sa NEEnevhodneE
  (model kazí diakritiku), parujeme cez id. Verbatim text inject LOKÁLNE z indexu.
- retry kaskáda per batch: celý → polovice → per-item; chybajúce id → log FAIL, ďalší tik
  doberie. Nikdy nefabrikuje verdikt.
- `llm_client` je v `toolkit/` tohto repa (stdlib), ďalšie cesty na sys.path netreba.
- launchd `pl.zolander.forget-audit`: StartCalendarInterval 04:15 (PO dream 03:00 čo plní
  frontu), NIE StartInterval — agent dobehne frontu a spí, netreba tikať á N min.
  `--all --notify` → po behu push report cez zolander_notify.py (fail-open). ProcessType
  Background, RunAtLoad false. Bootstrap: `launchctl bootstrap gui/501 <plist>`.
- Príkazy: `--once [--chunk N]` (tik), `--all` (celá fronta), `verify` (audit z disku:
  duplicity/poškodené/progress↔verdikty), `report` (text pre notify).
- integrity NEchráni skripty (len pub+fingerprint) → edit forget_audit.py loop nerozbije.
- CESTY (overéné 2026-09-29): venv s torch = `~/projects/zolander/.venv-yar/bin/python`
  (NIE ~/zolander/...); `zol_mem.py recall` číta JSON zo **stdin** `{query,topk,source}`,
  NIE argv — na priame volanie z Pythonu monkeypatch `sys.stdin=io.StringIO(json...)` a
  zavolaj `cmd_recall()` (vytlačí hity, vráti None). sandbox: nič nepipuj do stdin cez shell.
- APPLY overéný end-to-end: promote #1771/#1062 boli dormant salience 0.0 → po apply
  `active:true`, recall ich vracia na 1.-2. mieste. forget → retired = mäkké, DB nedotknutá.
  DIER v Opus verdiktoch (podrž v hlave, reverzibilné): občas prestrelí identity nálepku
  na udalosť/gastro (napr. šalát #2560), a promuje near-dup páry samostatne (#1304≈#1349,
  #1383≈#1872) — kandidát na budúci dedup krok pred apply.
TODO (čaká na vedúcka): `forget_audit.py apply` — aplikuje schválené verdikty (forget →
retire, promote → zmena kind na durable + obnova salience). ZATIAĽ NENAPÍSANÉ.

## RISK-TRIAGE APPLY (2026-09-29, oprava „human-in-the-loop nikde nie je")
VEDÚCKO trafil pascu: „caká na tvoje slovo" = to isté ako ránna iniciatíva — nič ho netlačí
prísť ku verdiktom → ležia navždy. Gate čo sa nikdy nespustí = alibi, nie poistka.
OPRAVA: `cmd_apply(do_write, include_identity)` dáva RISK-TRIAGE:
- AUTO-SAFE (agent aplikuje S+M, aj z launchd): forget→retired (mäkké, reverzibilné),
  keep→salience bump, promote→semantic/procedural (len durabilita, obsah nemení).
- GATED: promote→IDENTITY (jadro „kto vedúcko je" + Opus tam PRESTRELÍ (napr. parízak
  #2560 dostal identity 0.9 — a paradoxne vedúcko potvrdil že to identita JE, takže
  hranicu „gastro vs kus mňa" vie ťahnuť LEN človek)). Uloží do identity_pending.jsonl +
  pošle JEDNU WhatsApp správu; aplikuje sa až na `apply --apply --identity` („zrob identity").
- ANTI-SPAM: identity správa sa pošle LEN keď sa fronta ID zmenila oproti disku (denny
  re-run nespamuje). Fronta sa NIKDY nezasekne (auto-safe ide vždy).
- LAUNCHD prepísaný na `--cycle` (04:15): run(all) audit → cmd_apply(do_write,gate) —
  loop nie len navrhuje, ale VYKONÁVA bezpečné sam, identitu posiela. Test gate invariantov
  = izolovaný sandbox harness (docasny idx+verdikty, mock _push_text), 2/2 PASS naostro.

## Návrh: ďalší agent — všeobecný „pracovný LLM-tick" (paste vzor, durable-unattended-batch-jobs)
Zolander má dnes len pasívnych agentov (loop pozoruje, dream konsoliduje pamäť). Pre
veľké nočné úlohy __USER__ (audit, písanie kapitol zolo2.0, enrichment atómov) chýba
agent čo KONÁ prácu po ohraničených kusoch. Vzor (skill durable-unattended-batch-jobs):
kľúč je **fresh session/proces každý tick** → nikdy nenarazí na 200k kontext limit.

ŠTYRI KUSY:
- (a) PROGRESS na disku: `work/<uloha>/progress.json` {done, failed, total, next_chunk,
  uloha}. Zdroj pravdy — NIKDY nedôveruj self-reportu agenta, over z disku.
- (b) `zolander_work.py` (S LLM cez llm_client/agy stack): tick = načítaj progress →
  vezmi JEDEN chunk → fix+verify → atomický zápis (tmp + os.replace) → zapíš progress →
  EXIT. Idempotentný resume: `already_done()` testuje ŠTRUKTÚRU (počet riadkov + povinné
  polia), NIE hodnoty (inak prerobí staré legitímne položky).
- (c) WATCHDOG: pre Zolandera použi **launchd StartInterval** (konzistentné s loop/dream
  + prežije reštart Macu; Hermes cron žije len keď žije Hermes). LLM-tick v launchd je OK,
  lebo každý beh je nový proces.
- (d) `zolander_work.py verify` — ráno prejde VŠETKY výstupy z disku (counts, schéma),
  povie čo predrobiť. Green-check štýl.

PRAVIDLÁ (skill + __USER__ prostredie):
- LLM nikdy needituje verbatim zdroj čo sa má zachovať 1:1 — inject lokálne z inputu,
  model vracia len odvodené polia + index kľúč (inak zničí diakritiku/preklepy).
- Retry kaskáda per-kus: celok → polovice → per-item; nikdy nefabrikovať výstup, zaloguj FAIL.
- sandbox: „Operation not permitted" na súbore → zaloguj FAIL a choď ďalej, NECYKLI na tom
  istom flagnutom súbore (spustí bezpečnostný alert). Watchdog to redoi neskôr.
- Ak `zolander_work.py` pridáš do FILES v integrity.py, po každej zmene `integrity.py write`.

Reálne stavať až keď __USER__ povie KONKRÉTNU úlohu — chunk-logika a verify sa píšu na mieru.

## PASCA: claim_vs_dirty warn sa točí donekonečna (daemon noise, nie mŕtvy loop)
Honesty audit (`zol_honesty.check_claim_vs_git`) firuje keď úloha v `steps_done` tvrdí
commit/push v allowlist projekte a `git status --porcelain` je dirty. Dirty count čo
„dýcha" (napr. 27→33 každú pol hodinu) NIE je mŕtvy loop — je to ŽIVÝ watcher/daemon čo
za behu píše temp probe súbory (`_probe_*.ts` v `src/scripts/`, atď). Koreň = chýbajúci
`.gitignore` vzor, NIE bug auditu.

DVOJITÁ OPRAVA (2026-09-28, overené):
1. **git úroveň** — `.gitignore` vzor musí pokryť VŠETKY cesty kde daemon píše, nie len
   jednu. Turiec mal `scripts/_*` ale nie `src/scripts/_*` → probes tam prenikali.
   `git status --porcelain` gitignored súbory NEzobrazuje, takže gitignore = úplné umlčanie.
2. **audit úroveň** — `_dirty_count` ignoruje daemon/build noise centrálne:
   `IGNORE_DIRTY_BASENAMES=("AGENTS.md",)` (Next prepisuje každý `next dev` → inak firuje
   navždy) + `IGNORE_DIRTY_PREFIX="_"` (veduckova temp/probe konvencia).
   KĽÚČ: reálna práca prefix `_` NEMÁ → filter nezamlčí skutočný dirty (overené: 10KB
   `fill-missing-invoices.ts` bez prefixu správne firuje; umelý test raw=5→filtered=2).
   `git status` fail → `-1` (nefiruje, `-1 > 0` False).

POSTUP keď claim_vs_dirty visí: (1) `git status --porcelain` — čo reálne visí; (2) roztrieď
temp/probe (`_*`, auto-gen) vs reálna práca; (3) reálnu commitni PO sanit gate (verejný repo!),
temp zakry gitignore vzorom; (4) zosúlaď `steps_done` úlohy s diskom + zavri pending v ledgeri;
(5) over `zol_honesty.py --json` že warn zmizol (dôkaz z disku, nie self-report).
