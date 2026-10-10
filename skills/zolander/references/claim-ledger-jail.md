# Claim-ledger väzenie — zámok proti tvrdeniam čo dáta vyvrátia (2026-08-31, OVERENE)

Vedúcko: „no tak si stvor väzenie ktoré ti nedovolí tvrdiť nič čo ti potom dáta vyvrátia."
Dôvod vzniku: v jednej úlohe som 3× tvrdil load-bearing fakt a dáta ma vyvrátili —
zakaždým som to MOHOL lacno overiť a neurobil:
1. „IBIA provenance neexistuje" (spike meral index, nie DB — reálne 410/410 malo source)
2. „prázdne orphan vektory = bug" (fantóm, nulová norma=0)
3. „5 CONFLICTov v MELD" (4/5 falošné, Opus prestreľoval — cross-check ich schladil)

## Čo to je
`toolkit/claim_ledger.py` (čistý stdlib, ide aj offline pod /usr/bin/python3).
Load-bearing tvrdenie sa registruje s RE-SPUSTITEĽNOU kontrolou, čo číta ground truth
NEZÁVISLE od môjho slova. Tri stavy (NIE dva — §7.5 empty!=error!=false):
  VERIFIED     — pozorovanie tvrdenie potvrdilo
  REFUTED      — pozorovanie ho vyvrátilo
  UNVERIFIABLE — kontrola zlyhala/nedá sa spustiť (chýba cesta, výnimka)
GATE: batch je „hotový" LEN ak VŠETKY VERIFIED. **UNVERIFIABLE blokuje ROVNAKO ako
REFUTED** — to je jadro: nesmiem „mať pravdu z presvedčenia", keď som to neoveril.

## Kontroly (checks.*) — každá vracia (stav, dôkaz), NIKDY nevyhodí von výnimku
- `file_line_contains(path, lineno, substr)` — cituje file:line
- `grep_count(path, pattern, expected)` — počet zhôd == expected
- `jsonl_field_all(path, field)` — každý riadok má neprázdne pole (prázdny súbor=UNVERIFIABLE, nie OK)
- `temporal_superseded(old_id, by_id)` — zol_graph temporal: valid_until + superseded_by==by_id
- `cmd_exit(cmd_list, expected_exit, must_contain)` — argv (NIE shell, shell-safe), exit+substring
- `predicate(fn, label)` — ľubovoľný bool, výnimka -> UNVERIFIABLE

## Použitie
```python
from claim_ledger import Ledger, checks
L = Ledger()
L.claim("IBIA 410/410 source", checks.jsonl_field_all("state/mem_index.jsonl", "source"))
L.claim("#120 -> #109",        checks.temporal_superseded(120, 109))
ok, txt = L.gate(); print(txt)
assert L.all_verified()   # tvrdý zámok pred „hotovo"
```

## Test (Voyager: musí platiť mimo prípadu čo ho vyrobil)
`toolkit/test_claim_ledger.py` — aplikuje väzenie RETROAKTÍVNE na tie 3 zlyhania:
keby existovalo vtedy, muselo by ich zavrieť. `--demo` v samotnom module: pustí pravdu,
zavrie na lži AJ na neoveriteľnom. Oboje v `run_tests.py --offline` (PASS=17).

## Pointa
Toto NIE je „sľubujem opatrnosť" (to je vata). Je to štrukturálny zámok, čo cvakne:
tvrdenie sa nedostane do finálnej odpovede, kým ho nezávislé re-spustiteľné pozorovanie
nepotvrdí. Nedokáže zablokovať prózu mid-sentence (to nie je v architektúre — §7), ale
dokáže odmietnuť „hotovo", kým gate nie je zelený. Používaj na KAŽDÝ load-bearing claim
(X hotové / X neexistuje / X rozbité) pred záverečným hlásením vedúckovi.
