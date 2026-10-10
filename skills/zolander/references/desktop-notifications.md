# Klikateľné natívne macOS notifikácie (desktop) — Zolander → __USER__

Doteraz Zolander notifikoval len cez `zolander_notify.py` = inbox.md + push na WhatsApp.
Problém (vedúcko, 2026-08-12): kým nejde na WhatsApp, o dianí na Macu nevie. Riešenie =
NATÍVNA macOS notifikácia, klik na ňu otvorí HTML report v prehliadači.

## Nástroj: terminal-notifier (de-facto štandard, NIE osascript)
- `osascript display notification` vie ukázať banner, ALE klik naň NIČ neotvorí (len
  ho zhodí) — netreba ho na "klik → report".
- `terminal-notifier` (julienXX) je správna voľba: má `-open URL` (klik otvorí resource),
  `-sound NAME`, `-ignoreDnD`, `-title`, `-subtitle`, `-execute CMD`, `-group ID` (dedup),
  `-list ID` (vypíše reálne doručené notifikácie + Message stĺpec = OVEROVACÍ nástroj).
- Alternatíva (vlastná podpísaná .app s notifikáciami) = overkill a krehké na MDM Macu.

## Inštalácia (OVERENÉ 2026-08-12, shell-safe, žiadne sudo)
  /Users/__USER__/Applications/homebrew/bin/brew install terminal-notifier
- brew je USER-LEVEL (`~/Applications/homebrew`) → inštalácia do user cellaru, žiadny
  zásah do systémových/MDM oblastí, žiadne sudo.
- `terminal-notifier` je **bottled** (predkompilovaná binárka) → žiadna kompilácia,
  len stiahne + naleje. ~487 KB, 13 súborov. Mainstream (~89k inštalácií/rok).
- sandbox RIZIKO: nízke. sandbox stráži exfiltráciu/čítanie citlivých súborov — toto je opačný
  smer (download do user space). Jediné reálne riziko je sieťové (bottle z ghcr.io); ak
  MDM blokne doménu, je to čistý "connection refused" (NIE sandbox alert, nič sa nerozsvieti).
- Beží binárka: `/Users/__USER__/Applications/homebrew/bin/terminal-notifier`.
- macOS 27 pre-release warning z brew = kozmetika, bottle sa naleje správne.

## Príklad volania
  terminal-notifier -title "Zolander" -subtitle "ranny brief" \
    -message "..." -sound Glass -ignoreDnD -open "file:///.../report.html"
(pozn: sandbox pravidlo = jeden atomický prikaz, žiadne &&/;/bash -c — toto je jeden prikaz OK.)

## ⚠️ BUG — správa začínajúca na '-' = flag (NÁJDENÝ+OPRAVENÝ 2026-08-12)
terminal-notifier číta hodnotu `-message`/`-title`/`-subtitle` ZAČÍNAJÚCU na `-` ako
FLAG a ZOŽERIE celú správu → `Message=(null)`. A skoro KAŽDÝ brief bullet začína na
`- ` (`- loop: OK`, `- sen/abstrakt:`...) → banner by prišiel PRÁZDNY. Tichá bomba:
exit 0, príkaz "prešiel", ale obsah sa stratil (prejavilo by sa až zajtra o 8:00 naostro
— preto vedúcko povedal "over, nájdi bug", a bol tam).
FIX v `zol_desktop_notify.py` `_guard_dash(s)`: ak `s.lstrip().startswith("-")`, predsad
U+200B (zero-width space, v banneri neviditeľný) → zruší flag-parsing. Chráni message,
title aj subtitle. Celý brief prejde (začína "Zolander..." nie '-', guard ho nechá tak).
OVEROVACIA METÓDA (dôkaz, nie exit kód): `terminal-notifier -list <group>` → Message
stĺpec. Pred fixom `(null)`, po fixe plný text. VŽDY over cez `-list`, nie "nespadlo".

## ⚠️ PITFALL — PRVÉ spustenie macOS "zožral" (OVERENÉ 2026-08-12)
Prvé volanie terminal-notifier ukáže LEN dialóg "terminal-notifier chce zobrazovať
notifikácie" a samotnú notifikáciu PREHLTNE (žiaden text, žiaden zvuk). To NIE je bug
ani chyba binárky — je to štandardné macOS povoľovanie. Až PO odklepnutí povolenia
druhé volanie ukáže reálny obsah + zvuk. Preto:
- NEHLÁS "funguje" po prvom vystrelení — over až druhým volaním po povolení.
- Na MDM Macu môže byť default štýl "Žiadne" / appka skrytá: Systémové nastavenia →
  Notifikácie → terminal-notifier → "Povoliť notifikácie" ON + štýl Bannery/Upozornenia
  + "Prehrať zvuk" ON. Ak vedúcko hlási "banner je, zvuk nie" → zvuk je vypnutý tam.

## ✅ POSTAVENÉ A OVERENÉ NAOSTRO (2026-08-12) — už nie návrh
- `toolkit/zol_desktop_notify.py` — vrstva. Args: `--title --subtitle --message
  [--report <path.md>] [--sound NAME]`. Ak dostane `--report`, spraví stdlib md→HTML
  (dark theme) do `state/reports/<base>.html` a klik na banner ho otvorí (`-open file://`).
  Fail-open, stdlib, `/usr/bin/python3`. terminal-notifier hľadá cez TN_CANDIDATES
  (launchd má orezaný PATH). md→HTML zvláda #/##/### nadpisy, `- `/`•` odrážky, **bold**,
  `---` → hr, *em*.
- Napojené do `toolkit/zolander_notify.py` → `fire_desktop()` v `main()` hneď po inbox
  zápise, PRED pushom. Takže KAŽDÁ notifikácia (brief/watchdog/initiative — všetky idú
  cez zolander_notify) dostane banner AUTOMATICKY. zolander_notify teraz parsuje aj
  `--report` a `--sound`. Reťazec overený v notify.log:
  `desktop | banner ok (report=ano)` → inbox → PUSH ok.
- Zvuky (kadencia podľa naliehavosti): `zol_brief.py` posiela `--report brief_<dnes>.md`
  BEZ zvuku (nebudí); `zol_watchdog.py` `--sound Sosumi` (niečo horí); clarify hook
  `--sound Ping`; done hook `--sound Glass`.
- BONUS: push na WhatsApp funguje aj z CLI (home channel), takže test dorazil aj na mobil.

## ✅ KLIK NA HOTOVÝ HTML report (nielen md→html) — 2026-08-20, OVERENÉ
Pôvodne `zol_desktop_notify.py --report <x>` robil VŽDY md→HTML (build_report). Ale
niektoré daemony (napr. flat-rent-toolkit) už generujú BOHATÝ HTML report (Leaflet mapa +
karty) — ten je oveľa lepší než jednoduchý md→html. Doplnené:
- `report_url_from_path(p)` — ak `p` je http/https/file:// → vráti tak; ak existujúci
  súbor → `file://abs`; inak None.
- `main()` priorita: `--report-url` > `--report` čo je HTML (`.html/.htm`) alebo už URL
  (použije priamo) > `--report` .md (spraví md→html ako predtým). Spätne kompatibilné.
Takže daemon pošle `--report /abs/cesta/report.html` a klik otvorí presne ten pekný HTML.

## ⚠️ SILENT BUG — `report=` sa musí THREADNÚŤ cez KAŽDÝ caller wrapper (2026-08-20)
Reálny prúser (vedúcko: "klik na report chýba"): flat-rent watcher volal svoj tenký
wrapper `notify.send(text, subject=...)`, ktorý NEMAL parameter `report` → do
`zolander_notify.py` sa `--report` NIKDY neposlalo → banner vždy bez `-open` → v
`notify.log` VŽDY `banner ok (report=nie)`. Klik tam mesiace proste NEBOL, nedalo sa to
"prehliadnuť". DIAGNOSTIKA: keď vedúcko hlási "klik nefunguje", NEHÁDAJ — `tail notify.log`
a pozri `report=ano/nie`; ak `nie`, chyba je v REŤAZCI odovzdania reportu, nie v terminal-
notifier. Prejdi CELÝ reťazec caller→wrapper→zolander_notify→zol_desktop_notify a over, že
`report`/`--report` prežije každý skok. Prenosné: pri viacvrstvovom notify volaní pridanie
argumentu do najspodnejšej vrstvy NESTAČÍ — každý medzičlánok ho musí explicitne preposlať.
Dôkaz opravy = `report=ano` v notify.log po reálnom behu, nie exit 0.

## CLI notifikácie "skončil som / clarify" — kde sa DÁ a kde NIE (overené v zdroji)
- `pre_tool_call` hook s matcherom na nástroj `clarify` → notifikácia keď dávam clarify. PEVNÉ.
  Skript HOTOVÝ + otestovaný + ZAREGISTROVANÝ (2026-08-12): `toolkit/hook_clarify_notify.py`
  (parsuje tool_name==clarify + question z tool_input, vystrelí banner "caka na tvoju
  odpoved" + Ping, vždy prázdny stdout = NEBLOKUJE tool).
- `pre_verify` hook → notifikácia keď končím ťah čo MENIL súbory. PEVNÉ. Skript HOTOVÝ +
  ZAREGISTROVANÝ: `toolkit/hook_done_notify.py`. Fire LEN `extra.coding==true` A
  `extra.attempt==0` (raz za ťah, nie pri každom verify-nudgi; overené: attempt=1 nevystrelil).
- Čistá KONVERZAČNÁ pauza (odpoveď/rada bez editu, bez clarify) → Hermes CLI NEMÁ
  turn-end/idle event na zavesenie notifikácie (pre_verify fíri LEN na file-editing ťahoch).
  NEsľubovať "notifikuj po každej odpovedi" cez soft prompt — to už raz zlyhalo (ACK
  experiment). Buď hook, alebo nič. Detaily kontraktu: skill hermes-shell-hooks.

## ⚠️ done-hook PITFALL — "čakám na zadanie" klame pri ručnom teste (vedúcko to chytil)
Text "Hotovo, upravil som N súborov. Čakám na ďalšie zadanie." je NATVRDO v hook_done_notify
a SPOLIEHA sa, že pre_verify fíruje len pri reálnom konci file-editing ťahu. Pri RUČNOM
teste hooku (fake payload zo súboru uprostred práce) banner KLAME, že som skončil, hoci
pracujem ďalej — vedúcko to spozoroval a mal PRAVDU pomenovať to. Pri ladení testuj cez
fake payload zo súboru (shell-safe, nie heredoc), ale VEDZ že to nie je reálny koniec, a
povedz to vedúckovi rovno (F11: priznaj vlastnú chybu, nekecaj).

## Registrácia CLI hookov — HOTOVÁ (2026-08-12), postup pre budúcnosť
Vedúcko dal "hrab sa, urob to a všetko" → zaregistrované naostro. Postup (drž pri budúcich):
1. Skript hotový + otestovaný fake payloadom zo súboru (clarify: tool_name+question;
   done: extra.coding/attempt/changed_paths).
2. Textový helper (config.yaml je CHRÁNENÝ pred patch/write tolmi) pridá command pod
   existujúci event — clarify pod `pre_tool_call` (matcher: clarify), done pod `pre_verify`.
   Viac hookov na jeden event je OK (kotva = presný riadok `  pre_tool_call:` / `  pre_verify:`).
3. Re-approve: `HERMES_ACCEPT_HOOKS=1 hermes chat -q ok --source hooktest`.
4. `hermes hooks doctor` → chce "✓ allowlisted" + "✓ ran clean with empty stdout —
   observer-only" na oboch. "observer-only" je SPRÁVNE (nemajú vracať JSON).
5. Hooky fírujú AŽ od ĎALŠEJ session (v aktuálnej bežia staré registrácie) — nie bug.
Postup registrácie hooku (allowlist, path pitfally, revoke+re-approve pri stale hashe):
skill hermes-shell-hooks.
VEDĽAJŠÍ NÁLEZ: `hook_recall.py` mal stale allowlist hash (upravený 2026-08-10, doctor
warning "modified since approval"). Fix = `hermes hooks revoke "<presný command>"` →
`HERMES_ACCEPT_HOOKS=1` turn → `hermes hooks doctor` (chce "All shell hooks look healthy").
Osviežené 2026-08-12 na vedúckov pokyn.
