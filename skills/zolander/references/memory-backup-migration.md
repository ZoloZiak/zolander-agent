# Záloha a migrácia Zolanderovej pamäte (HyperspaceDB) — overené pasce

Kontext: refaktor pamäte 4→1 kolekcia (zol_semantic/episodic/procedural/identity →
jedna `zol_mem` + `memory_type` v meta). Tieto pasce sa ukázali NAOSTRO 2026-08 pri
pokuse o zálohu pred migráciou. Čítaj PRED akoukoľvek zálohou/migráciou pamäte.

## 1. Vektory sa NEDAJÚ spoľahlivo prečítať z tejto verzie servera
- `getPoints` — cez SDK (`hs.mjs get <col> <ids>`) AJ cez MCP (`hyperspace_get_points`)
  — hodí `5 NOT_FOUND: Collection '<x>' not found` NA KOLEKCII, ktorú `list` normálne
  vidí (count > 0). Je to rovnaká trieda bugu ako text-write/text-search (server bez
  embedding enginu). NESPOLIEHAJ sa na getPoints na dump ani zálohu.
- Funguje LEN `search`: `hs.mjs search <col> <topK>` (stdin {vector}) alebo
  `zol_mem.py recall` (embedne query a spraví search). Embedni široký neutrálny dotaz,
  topK=50 → vráti body s meta (vrátane textu).
- ALE `search` NIE je deterministický dump — vráti MENEJ než count (videné: 13 z 16
  procedural). Na úplnú zálohu treba VIAC rôznych dotazov + dedup podľa id, a aj tak
  nemusí byť 100% úplná. Preto zálohu ber ako "best effort text dump", nie ako verný snapshot.

## 2. Migrácia = RE-EMBED, nie kópia vektorov
- Keďže vektory sa nedajú spoľahlivo prečítať a preliať 1:1, správny postup migrácie:
  zálohuj TEXTY (z meta cez search) do JSONL → pri migrácii text RE-EMBEDNI cez
  embed_yar nanovo → vlož do novej kolekcie. Pre fakty <300 zn. (skoro všetky) je
  re-embed identický vektor, takže recall sa nezhorší.
- Pred insertom do Lorentz kolekcie NEZABUDNI na hyperboloid re-projekciu (viď
  ziak-local-ai-stack §9): x0 = sqrt(1 + Σ z_i²) vo float64, inak server odmietne
  "not on unit hyperboloid".

## 3. embed_yar progress bar rozbíja JSON parse
- embed_yar tlačí `Loading weights: ...%` na stdout → mieša sa do JSON výstupu recall/embed
  a `json.loads` padne na "Extra data". VŽDY presmeruj čistý JSON do súboru a progress zahoď:
  `... zol_mem.py recall < q.json > out.json 2>/dev/null`, potom čítaj out.json.
- Nedávaj JSON cez `echo '...' |` do stdin v shelli — slovenské znaky/úvodzovky rozbijú
  quoting (videné "Extra data: column 6"). Zapíš query do súboru a `< q.json`.

## 4. Lokálny mem_index.jsonl NIE je zdroj pravdy
- `~/projects/zolander/state/mem_index.jsonl` je NEúplný (menej riadkov než DB count — videné 15 vs 25)
  a znečistený: junk záznamy ("TEST writeback debug fakt - zmazat"), neplatné kind mimo
  KIND_COL ("pattern"). Nepoužívaj ho na rozhodnutie čo je v DB — over priamo cez search.

## 5. V starej pamäti je balast — pred migráciou triage SO súhlasom vedúcka
- Časť starých ~25 záznamov sú test/junk/duplikáty. Keďže plný beh zol_writeback nasype
  147 čerstvých kvalitných faktov, migrovať naslepo aj balast je zbytočné. ALE čo je "junk"
  NErozhoduj sám (pravidlo: veľké side-effects a mazanie z pamäte len so súhlasom) —
  VYPÍŠ vedúckovi zoznam záznamov a nechaj ho škrtnúť, potom migruj len ponechané.

## 6. Poradie krokov (dohodnuté s vedúckom 2026-08)
Migráciu 4→1 rob KÝM je pamäť malá (~25 záznamov), NIE po naplnení — potom by si migroval
veľký objem. Poradie: záloha textov → migrácia 4→1 (re-embed) → prepoj zol_mem.py
(KIND_COL→jedna kolekcia, col_for, recall bez fan-out, remember zapíše memory_type) +
hook_recall/dream/zol_session → over recall → P2 dedup poriadny (recall-check pred remember,
merge/skip; vedúcko NEchce "jednoduchý" dedup) → až potom plný beh zol_writeback naostro.
P3 graf / P4 benchmark geometrie / P5 hybrid retrieval / triage skillov AŽ na naplnenej
pamäti (na prázdnej sa recall nedá merať).

## 7. zol_writeback extrakčný model = opus (nie gpt-mini)
Vedúcko chce najvyššiu kvalitu extrakcie (LLM je zadarmo). Default `ZOL_WB_MODEL` v
zol_writeback.py je zmenený na "opus". Opus ťahá aj kauzálne "prečo" (napr. "toto 2,5 dňa
zabíjalo loop") — citeľne bohatšie než gpt-mini. Prepísateľné cez env na lacnejší beh.
