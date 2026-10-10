# MoA review zapojený do pre_verify hooku + diagnostické okno (2026-08-15, OVERENE)

Vedúcko chcel: „zapoj reviewer VŠEOBECNE (default ON, nech to je open) + diagnostické
okno kde sa loguje VŠETKO čo sa deje." Postavené a otestované naostro. Toto je vzor
„LLM review ako brána pred "hotovo"", nie jednorazovka.

## Čo sa zapojilo
`toolkit/hook_verify.py` (Hermes `pre_verify` hook) má teraz DVE vrstvy:
1. **Mechanická** (vždy, zadarmo, deterministická): parsujú sa zmenené `.py`/`.json`?
   Nie → `{"action":"continue"}` s chybou. Ako doteraz.
2. **MoA LLM review** (NOVÁ, default ON): ak kód parsuje, `zol_eval.evaluate(...,
   generator="opus", eval_system=REVIEW_SYSTEM)` → gpt+gemini (NIE opus, aby nehodnotil
   sám seba) skórujú zmenené `.md`/kód na AI-slop, sycophancy, bohemizmy, diery. Pod
   prahom (default 0.6) → continue s výčitkou.

## Prečo A (v hooku) a NIE len volateľná knižnica — a čo to stojí
Vedúcko vedome zvolil default-ON v hooku (beží pri KAŽDEJ mojej odpovedi s editom, aj
cez WhatsApp gateway). Cena: prvý edit v úlohe +30-60s (dva LLM cez Palantir proxy),
riziko 429 pri veľkej session. Preto POVINNÉ poistky nižšie. Alternatíva B (volať
`zol_eval` ručne na konci roboty, kde mám plný kontext) je lacnejšia — ak to niekedy
preáča, prepni späť na B cez `ZOL_VERIFY_MOA=0`.

Vedúckov kľúčový postreh pri návrhu: „recenzenti by mali dostať najprv CELÝ kontext."
To je presne dôvod prečo hook NIE je ideálne miesto — `pre_verify` proces dostane na
stdin len `{changed_paths, coding, attempt, cwd}`, NIE konverzáciu ani zámer. Takže
recenzent v hooku súdi po-súbore (celý obsah zmeneného súboru + krátke generické
zadanie), nie podľa toho PREČO sa to menilo. Plný-kontextový review = cesta B.

## POISTKY (všetky v kóde, overené)
- **default ON, vypína `ZOL_VERIFY_MOA=0`** (`os.environ.get("ZOL_VERIFY_MOA","1")=="0"`).
- **throttle**: `ZOL_VERIFY_MOA_COOLDOWN` (default 120s) cez stamp `$TMPDIR/zol_moa_stamp`
  → séria editov nespustí kopu volaní.
- **len attempt 0** (nudne raz), **max 2 súbory**, **200–20000 znakov** (drobnosti/obrie preskočí).
- **rozbitý kód → MoA sa NEspustí** (najprv oprav syntax mechanickou vrstvou, netreba naň LLM).
- **env self-load**: hook beží pod `/usr/bin/python3` BEZ `.zshrc` → sám načíta
- **SIGALRM watchdog** `ZOL_VERIFY_MOA_BUDGET` (default 90s) + **fail-open VŠADE**: LLM
  zamrzne/zlyhá/429/timeout → ticho pustí ďalej, hook NIKDY nezhodí turn.

## ⚠️ PITFALL: hook `timeout:` v configu MUSÍ prevýšiť LLM budget (inak Hermes zabije v polovici)
`hooks.pre_verify.<N>.timeout` v `~/.hermes/config.yaml` bol **30s**, ale MoA budget je
90s (dva LLM cez proxy reálne trvajú ~30-60s). Hermes by hook zabil skôr než review
dobehne → review by sa NIKDY nedokončil, tichý no-op. FIX: `hermes config set
hooks.pre_verify.1.timeout 100` (index 1 = hook_verify, index 0 = hook_done_notify).
PRENOSNÉ: každý hook čo volá LLM/sieť potrebuje config `timeout` > interný SIGALRM budget,
inak vonkajší zabijak vyhrá. Zlaď: budget < config-timeout (90 < 100).

## Diagnostické okno — verify_dashboard.py
`toolkit/verify_dashboard.py` (stdlib `http.server`, žiadne závislosti). Číta
`logs/verify.jsonl` a servuje živý dashboard na `http://127.0.0.1:8790` (fetch /events
každé 2s, farba podľa typu, počítadlá block/pass/error, auto-scroll).
Spustenie: `/usr/bin/python3 toolkit/verify_dashboard.py [port]`.

`hook_verify.py` teraz loguje KAŽDÝ krok cez `_log(ev, **kw)` do `logs/verify.jsonl`
(JSONL, fail-open): `fired` → `mechanical_block` / `moa_start` → `moa_file` (celkom +
per-judge skóre) → `moa_pass` / `moa_block` / `moa_error` / `moa_disabled` / `moa_skip`.
Dá sa aj grepovať priamo. Overené naostro: slop `.md` (bohemizmy + vata) dostal 0.00/1.0,
gpt+gemini pomenovali „mieša češtinu, AI-slop, superlatívy"; čistý súbor `moa_pass`.

## Durable?
Dashboard je zatiaľ TERMINÁL proces (zhasne so session). Ak ho vedúcko chce 24/7 ako
ostatné daemony → sprav launchd agenta `pl.zolander.verifydash` (vzor ako gemma daemon:
plist do `~/Library/LaunchAgents` + `launchctl bootstrap`, KeepAlive). Zatiaľ NIE durable.
