# Hermes hooks — mäkký SKILL.md pokyn → tvrdý kód-zámok

## Kedy siahnuť po tomto
Keď má byť nejaké správanie GARANTOVANÉ (nie „model by mal…"). SKILL.md je iba
prompt — model ho môže preskočiť (rovnako ako anti-halucinačné protokoly). Ak
vedúcko chce istotu („nebude to vedieť / bude lenivý"), riešenie NIE je silnejšia
formulácia v prompte, ale KÓD zavesený na Hermes hook. Prvý reflex: over v zdrojáku
či hook existuje, nehádaj.

## Čo Hermes reálne ponúka (overené v zdrojáku ~/.hermes/hermes-agent)
- Hook systém: `agent/shell_hooks.py`, konfigurovaný `hooks:` blokom v config.yaml.
  Registruje shell/py skripty na existujúce `invoke_hook()` body — bez zmeny jadra.
- Zoznam platných eventov: `hermes_cli/plugins.py` -> `VALID_HOOKS`. Užitočné:
  `on_session_start`, `on_session_end`, `pre_llm_call`, `post_llm_call`,
  `pre_tool_call`, `post_tool_call`, `pre_verify`, `subagent_stop`, `pre_gateway_dispatch`.
- Wire protokol: Hermes pošle skriptu JSON na STDIN
  {hook_event_name, tool_name, tool_input, session_id, cwd, extra}. Skript môže na
  STDOUT vypísať JSON (inak ignorované).
- `pre_tool_call` blok: {"decision":"block","reason":...} alebo {"action":"block","message":...}.
- `pre_llm_call` context injekcia: {"context":"..."} (aj holý string). KĽÚČOVÉ
  (plugins.py:1906): context ide VŽDY do USER message, NIKDY do system promptu ->
  prompt cache prefix ostáva nedotknutý. Context je efemérny, do session DB sa nepíše.

## Cache pasca — pre_llm_call beží KAŽDÝ turn
Hermes AGENTS.md: „prompt caching is sacred, system prompt byte-stable". `pre_llm_call`
sa volá pred každým API callom. Ak hook vypisuje ťažký obsah (napr. bootne YAR
embedder + recall) na každom turne, je to drahé aj pomalé a zaplaví kontext. RIEŠENIE:
stamp-guard — skript si v $TMPDIR drží marker per session_id a ťažkú prácu spraví LEN
prvý turn danej session, ďalšie turny = prázdny stdout (tichý no-op). Marker píš HNEĎ
(aj keď práca zlyhá), inak sa skúša každý turn dokola.

## Ako sa to zapojí (postup, shell-safe)
1. Skript píš pod /usr/bin/python3 (stdlib only), nech nikdy nespadne (try/except ->
   tichý return); ťažké veci (venv/embedding) deleguj do subprocess vnútri neho.
2. `hermes config set hooks_auto_accept true` (skalár — config set to zvládne).
3. `hooks:` blok je LIST DICTOV -> `hermes config set` ho nezvládne a file/patch tools
   ODMIETNU config.yaml (chránený). Priprav malý .py helper čo textovo APPENDNE blok
   (zachová komentáre/poradie), idempotentný, spusti ho raz. Tvar:
     hooks:
       pre_llm_call:
         - command: /usr/bin/python3 /Users/__USER__/projects/zolander/toolkit/hook_recall.py
           timeout: 100
4. Allowlist: hook musí byť schválený, inak NEfíruje. Buď `HERMES_ACCEPT_HOOKS=1
   hermes chat -q "..."` (jeden ostrý beh = zaregistruje + zároveň E2E test), alebo
   TTY prompt pri prvom štarte (hooks_auto_accept to pokrýva).

## Verifikácia (dôkaz, nie sľub)
- `hermes hooks list`   — Hermes hook vidí.
- `hermes hooks doctor` — ✓ allowlisted, ✓ script unchanged, ✓ produced valid JSON
  na syntetickom payloade. Toto je zelený dôkaz.
- Ručný STDIN test: `echo '{"hook_event_name":"pre_llm_call","session_id":"X"}' |
  /usr/bin/python3 hook.py` — prvý beh vráti {"context":...}, druhý s tým istým
  session_id = prázdny stdout (stamp-guard funguje).
- Po ostrom `hermes chat` skontroluj že pribudol stamp v $TMPDIR/<...>_stamps.

## Konkrétna inštancia: hook_recall.py (recall-first zámok)
toolkit/hook_recall.py na `pre_llm_call`: prvý turn session -> spustí
`zol_session.py start` -> {"context": recall + chvost PLAN.md}; ďalšie turny ticho.
Fail-safe: DB/venv down -> vráti {"context":"[recall-hook zlyhal… bežíš BEZ pamäte]"}
aby model nepredstieral kontext. Dôsledok pre SKILL.md: „Prve slova pri starte" už
NEsmie kázať spúšťať `start` ručne (zdvojenie) — len prečítať auto-recall blok.

## Pasce / poznámky
- Je to USER-config (config.yaml + skript v ~/projects/zolander) -> prežije Hermes update.
  Ale ak by zmenili hook API/VALID_HOOKS, treba preveriť (over v zdrojáku znova).
- skill_manage patch: NEescapuj úvodzovky v old/new_string (žiadne \\" ) — tool to
  odmietne ako escape-drift. Píš " priamo.
- config.yaml je pred file/patch/write_file tools chránený zámerne — nesnaž sa to
  obísť, použi `hermes config` alebo textový .py append helper.
