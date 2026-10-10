# Ohraničený autonómny loop nad viacerými projektami (cron + manifest + picker)

Vzor keď vedúcko povie „choď autonómne do nekonečna, mám X hodín roboty bezo mňa,
hlás progres cez WhatsApp" (napr. „totálny refactor všetkých projektov"). Overené
2026-08-15 na 12h auto-refactor loope nad 6 projektami.

## Prvé: preformuluj „do nekonečna" na OHRANIČENÉ (F11, nie poslušnosť)
„Nekonečný samobežný loop čo edituje N repozitárov" = najrýchlejšia cesta rozjebať
projekty kým vedúcko spí + rate 429. Povedz to rovno a nastav BOUND:
- Časové okno → počet tickov (napr. 12h @ 20min = 36 tickov). `max_ticks` v manifeste,
  loop sa po ňom SÁM zastaví a pošle „dobehol, ráno si to prejdeme".
- Na `main` NIKDY, `git push` NIKDY, `--force` NIKDY — aj keď vedúcko povie „naostro".
  Keď odchádza, artefakty sú TEMP; reálne fixy len na vetve `zolander/auto`.

## Per-projekt politika — NIE uniformný refactor
Obhliadni terén PRED stavbou (`git -C <p> status --porcelain --branch` na každom):
- git repo + ČISTÝ main → `mode: fix_branch` (reálne fixy na vetve zolander/auto).
- git repo s UNCOMMITTED zmenami na main → `mode: analyze_only` (nezhodiť živú prácu!).
- BEZ gitu (žiadna záloha) → `mode: analyze_only` (read-only, len návrhy do .md).
- `~/projects/zolander` (živý systém: daemony/hooky/pamäť bežia počas toho) →
  `analyze_only`. Refaktorovať sám seba za behu naslepo = podrezať si vetvu.
Zapíš politiku do `~/projects/refactor/auto_review/_manifest.json` (projects[],
rotation[], cursor, tick, max_ticks, hard_rules[]). Cron prompt tak ostane krátky
a deterministický — číta mode z manifestu, nehádže rozhodnutie na model.

## SCOPE GATE — keď správnosť artefaktu overí LEN oko a to oko nie je k dispozícii
Projekt kde sa výsledok dá overiť iba vizuálne (renderer, UI, farby, FPS) a za behu to
nevidíš (sandbox zamkol screencapture, vedúcko spí) → loop NESMIE meniť tú vizuálne-overiteľnú
plochu naslepo. „Skompiluje sa\" NIE je dôkaz že renderuje — kód beží čierno a 24h to nikto
neuvidí. Zúž mandát na to čo sa dá dokázať bez oka:
- Refactor LEN mechanické, COMPILE-DOKÁZATEĽNÉ extrakcie (extract method/trieda/konštanta),
  semantika bit-identická. ZÁKAZ meniť render-logiku, poradie encoderov, math, PSO/depth/blend
  stavy, buffer formáty, default hodnoty flagov.
- Čokoľvek čo sa overí len okom (vizuálna parita, farba, FPS) → NEMEŇ, zapíš návrh do
  `auto_review/ACTION.md` pre vedúcka. Strážca k dverám čo nevieš otvoriť = tipovanie.
- Brána po KAŽDEJ zmene: `javac @args` exit 0 (alebo ekvivalent) + `git diff` review; červená
  → `git checkout -- <súbor>` + zápis do `BLOCKED.md`, NEcommituj. Standalone offscreen
  proof/test čo beží bez GUI (napr. `java` FFM proces ~2s na M4) je jediná regresná sieť —
  zmeraj baseline PRED refaktorom, nefabrikuj číslo („neslo spustiť\" je platný výsledok).

## Mechanika: cron `script` picker → stdout do promptu
- `~/.hermes/scripts/refactor_loop_picker.py` (/usr/bin/python3 stdlib): vyberie ďalší
  projekt v rotácii, atomicky posunie cursor+tick (os.replace na .tmp), vypíše JSON brief
  na stdout. Pri tick>=max_ticks vypíše `LOOP_DONE:` s pokynom poslať finálnu správu a
  skončiť. Cron injektuje tento stdout do promptu ako kontext (data-collection vzor).
- Cron job: `schedule='every 20m'`, `repeat=36`, `script='refactor_loop_picker.py'`,
  `enabled_toolsets=['terminal','file','delegation']`. Prompt = kompletná Zolander persona
  + tvrdé pravidlá + rozvetvenie podľa `mode` + „finálna odpoveď 2-4 riadky na WhatsApp".
- DURABLE (prežije pád session/PC) — presne to čo vedúcko chce (nie subagenti, tí zomrú
  s parent session; nie táto session, tá narazí na 200k kontext a spadne na 429).

## PITFALL — cronjob create nechá job NEPINNUTÝ → tichý skip pri model drifte
`cronjob_manage action=create` (aj tool) vráti `model: null, provider: null` — nástroj
model nastaviť NEVIE (user-owned pole). Nepinnutý cron beží na `model.default` v čase
firovania; ak sa default odvtedy posunul na model čo neexistuje/nefunguje, tick sa TICHO
skipne a 24h loop nič neurobí. FIX hneď po create: pin cez CLI
`hermes cron edit <id> --model <plný model id> --provider <provider> --pin`. Aktuálny
model NEzistíš cez `hermes model` (odmietne non-interactive) — prečítaj `~/.hermes/config.yaml`
(`model.default` + `model.provider`). Over že pin pristál: v `~/.hermes/cron/jobs.json` je
`model`/`provider` nie null (CLI edit output `pinned` nemusí odzrkadliť, rozhoduje jobs.json).

## PITFALL — cron `deliver='all'` z CLI NEDORUČÍ
`deliver='all'` (aj `'origin'`) z CLI session → `last_delivery_error: "no delivery target
resolved for deliver=all"` (CLI nemá resolvnuté home kanály). FIX: explicitný cieľ
`deliver='whatsapp:48000000000@s.whatsapp.net'`. VŽDY over test tickom (`cronjob action=run`)
+ skontroluj `last_delivery_error` v odpovedi + `hermes send --to whatsapp "test"`.

## PITFALL — picker prepíše manifest medzi write a patch
Ak testuješ picker naostro, prepíše cursor/tick v manifeste. Po teste znovu prečítaj
manifest z disku (patch zlyhá na stale obsahu / „modified since last read") a vynuluj
cursor:0, tick:0, started_at:null pred ostrým spustením.

## Overenie že loop reálne robí (nie prázdny beh)
Nespoliehaj sa na „status ok". Po prvom tick-run over: (a) `.md` súbor s nálezmi vznikol
a má obsah, (b) commit padol na `zolander/auto` a `git log main` je NEZMENENÝ (posledný
commit na main je stále vedúckov), (c) WhatsApp správa reálne dorazila. Až potom pusti
vedúcka od PC.

## Konsolidácia na konci (keď loop dobehne)
6× dlhé per-projekt `.md` (kľudne 1500 riadkov) sú neúnosné na čítanie. Vyrob JEDEN
`auto_review/ACTION.md` zoradený PODĽA DOPADU, nie podľa projektu:
P1 = treba rozhodnutie vedúcka (nezvratné/dizajnové) · P2 = veľké nálezy (viem fix na vetvu)
· HOTOVÉ (commity na vetve čakajú na merge) · dokumentačné projekty (desync/logika).

## Keď vedúcko na konci povie „všetko robíš sám" (2026-08-16)
NIE je to blanket na bezobslužný deploy. „Sám" znamená DOŤAHAJ, nie schovaj sa za otázky
ANI nedeployuj naslepo. Drž tri čiary aj pri „sám":
1. Projekt čo auto-deployuje z `main` (turiec → Vercel): fix na vetvu áno, merge/push na
   main NIE bezo slova. A ak fix vyžaduje ROZHODNUTIE (napr. aký auth model: env token /
   Supabase Auth / cookie) → NEHÁDAJ, vypýtaj jedno slovo — zlá voľba zamkne usera alebo
   otvorí dieru. To je jediné čo naozaj potrebuješ od neho; všetko ostatné sprav.
2. Projekt s uncommitted živou prácou → nedotýkaj sa git stavu, počkaj kým stashne/commitne.
3. Osobný obsah (kniha, zdravotné/právne poznámky) → nekonaj autonómne, jeho doména.
Zvyšok (izolované bezpečné fixy S TESTOM) sprav SÁM a otestuj naostro.

## Turiec admin auth-guard fix (2026-08-16, overený vzor na vetve zolander/auto)
Keď loop nájde „admin routes bez server-side auth\" (real: /api/admin/* mazalo entity
bez kontroly, heslo+token hardcoded v client bundli):
- FIX DRY: jeden zdieľaný helper `src/lib/admin-auth.ts` `requireAdmin(request)` vracia
  NextResponse(401/500) alebo null; každá route na začiatku `const denied =
  requireAdmin(request); if (denied) return denied;`. NEKOPÍRUJ check do N súborov.
  Fail-closed: keď `ADMIN_PASSWORD` nie je v env → odmietni všetko (nikdy prázdne heslo).
  GET routes bez `request` parametra → pridaj `(request: Request)`.
- ⚠️ Zamknutie API dverí ZAMKNE aj admin UI (klient posiela hardcoded Bearer v bundli) →
  po merge admin dostane 401 kým sa neoprav aj KLIENT (token z env/servera). Povedz to
  rovno pred deployom — je to nadväzný krok, nie hotovo.
- VERIFIKÁCIA v projekte s predexistujúcim TS dlhom: `npx tsc --noEmit` + `npx eslint
  <súbory>`. Turiec má ~60 predexistujúcich TS chýb v page komponentoch/telegram.ts →
  ROZLÍŠ svoje (0) od starých; `next build` by na starých spadol, tak over LEN zmenené
  súbory = poctivé ad-hoc overenie, NIE „suite green\". eslint exit 0 = čisto.

## Ne-git projekt: bezpečný edit bez zálohovej siete (2026-08-16, overené na zolo2.0)
Keď dostaneš zelenú robiť fixy aj v ne-git projekte (žiadna git záloha):
1. Over že NIČ z tej pipeline práve nebeží (`pgrep -fl <procesy>`) — edit súboru čo si
   worker importuje = rozbiješ bežiaci beh.
2. Pred KAŽDÝM editom `cp subor subor.bak` (jeden atomický príkaz shell-safe).
3. Fix rob cez `patch`; pri komentároch NEklam o správaní (napr. „raise vnútri try sa
   NEretryuje ak except chytá len HTTPError" — over reálny control-flow, oprav komentár).
4. Po edite `py_compile` + REÁLNY funkčný test: malý skript do
   `~/projects/zolander/state/hermes-verify-*.py`, spusti cez `/usr/bin/python3` s
   `sys.path.insert(0,'<toolkit>')`, over PASS, HNEĎ zmaž. (cmd_guard blokuje `python -c`
   s `;`/zátvorkami — píš skript do súboru, nie inline.)
5. `.bak` nechaj kým vedúcko neoverí; do ACTION.md napíš „záloha: X.bak".
