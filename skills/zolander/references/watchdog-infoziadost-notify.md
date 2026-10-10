# Watchdog infožiadosti + terminal-notifier desktop notifikácie (2026-08-24)

## Prehľad
Kron jobs `0 9,15 * * *` behá jeden denne pre SVP a TURVOD infožiadosti. Kým nič nepríde, script vypíše nič (baseline → agent nebudí). Keď dorazí mail od `svp.sk` alebo `turvod.sk`, script:
1. Vypíše deterministický zoznam (`message-id\temail\tsubject`)
2. Vystrelí **natívny macOS banner** cez `terminal-notifier`
3. Agent sa v Hermes desktop chatu ozve s obsahom mailu

## Inštalácia (overené)
- `terminal-notifier`: `/Users/__USER__/Applications/homebrew/bin/terminal-notifier`
- Inštalovaný cez `brew install terminal-notifier` (user cellar, shell-safe)
- Rýchla vérka: ~487 KB, 13 súborov

## Prieduchy a oprava (overené 2026-08-12)
**BUG:** `terminal-notifier` číteľné hodnoty `-message`, `-title`, `-subtitle` začínajúce na `-` sú zachápané za flag → `Message=(null)`.
**FIX:** Predaná správ predsaď medzerou alebo použite `\u200b` (zero-width space):
```python
msg = message.lstrip()
if msg.startswith("-"):
    msg = "\u200b" + msg
```
Vždy overíme cez `terminal-notifier -list zol-infoziadost` → `Message` stĺpec nie je `(null)`.

## Príklad volania (zo scriptu watch_infoziadost.py)
```bash
/Users/__USER__/Applications/homebrew/bin/terminal-notifier \
  -title "Zolander — infožiadost" \
  -subtitle "Odpoveď úradu dorazila" \
  -message "SVP: v úseku sú splašky — potok sa odkryť nedá lacno" \
  -sound Sosumi \
  -ignoreDnD \
  -group zol-infoziadost
```

## Overovacia metóda (dôkaz, nie exit kód)
```bash
terminal-notifier -list zol-infoziadost
```
Ak `Message` stĺpec nie je `(null)` → banner obsahuje spravodajný text. Vždy over predpokládateľnou výstriľ.

## sandbox pravidlá
- Jeden atomický príkaz na volanie, žiadne `&&`/`;`/`bash -c`/`heredoc`
- Binárka sťahovaná cez `brew` do user cellaru (žiadny systémový zásah)
- `himalaya` + `terminal-notifier` sú v `/Users/__USER__/Applications/homebrew/bin/`

## Spájanie so Zolanderm
- Každá notifikácia (brief/watchdog/initiative) cez `zolander_notify.py` → `fire_desktop()` automaticky
- `--report` parameter preširá každým vrstvami caller→wrapper→zolander_notify→zol_desktop_notify
- Ak `report` neziveie → `notify.log` ukáže `report=nie`, chyba je v reťazci, nie v terminal-notifier