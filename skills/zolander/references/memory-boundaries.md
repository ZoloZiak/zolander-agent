# Pamäť — obsahové hranice (čo NEIDE do zol_mem)

## zolo2.0 knihu/atomy NEDUMPOVAŤ do zol_mem (2026-08-14, HARD PRAVIDLO)
Vedúcko občas povie „stiahni si moje myšlienky/atomy zo zolo2.0 do pamäte, to je môj
brain-dump, tak Zolander MUSÍ mať naplnenú identitu". NEROB priamy dump. Tri dôvody
(over si ich, NEsúhlas pre pohodlie — F11):
1. `memory_type=identity` v zol_mem = identita ZOLANDERA (kto SOM, tón, pravidlá, Ed25519),
   NIE žiakova. Napchať tam atomy ako „identity" identitu NENAPLNÍ — ROZPUSTÍ ju: na štarte
   každej session by som cez hook_recall čítal „som žiak a chcem to a to" namiesto
   „som Zolander mentor". Žiakove myšlienky sú VSTUP pre Zolandera, nie jeho identita.
2. Objem: zolo2.0 = 6110 atomov (~18× celá zol_mem, čo má ~329). 95% recallu by bol
   brain-dump backlog (META/štruktúra, „GOOGLE" to-research zoznamy, kryptické útržky) →
   prevádzková pamäť (ako staviame systém, sandbox, push) by zmizla pod šumom = zahltenie.
3. Duplikácia: atomy UŽ SÚ vo vektorovej DB kolekcii `lorentz129` (6110 vekt). Kopírovať
   do zol_mem = tá istá vec v dvoch kolekciách čo sa rozídu.

SPRÁVNE RIEŠENIA (keď chce aby Zolander „poznal jeho myslenie"):
- MOST (preferuj): napoj recall na `~/projects/zolo2.0/work` lorentz129 (cross-collection).
  Nič sa nekopíruje, Zolander nahliadne do myšlienok pri práci na KNIHE, nefarbí to jeho
  úsudok mimo knihy, nezahltí zol_mem.
- DESTILÁCIA ako TEMP artefakt na SCHVÁLENIE (nie priamy zápis): z `assignments_opus.jsonl`
  (gid→theme A-I × layer L1-L4 × conf) vyber nosné (L2/L3/L4, conf>=0.7, NIE META), po
  témach nech Opus vydestiluje ~5 jadrových myšlienok/téma (~40-48 spolu), UKÁŽ vedúckovi
  PRED zápisom. Ak schváli → ulož ako `semantic` (NIE identity). llm_client
  (`toolkit/llm_client.py`, má `system=` param) beží pod
  /usr/bin/python3 — stdlib urllib/ssl/http.client, NEPOTREBUJE requests.

## OBSAHOVÁ HRANICA — kniha je fikcia, zol_mem nie je (2026-08-14)
Kniha je literárny materiál. Čo si myslia a robia jej postavy, do MOJEJ operačnej pamäte
(čo mi cez recall formuje úsudok) NEIDE ako „žiakove myšlienky". Ak destilát vyzerá, že
presahuje fikciu do reálnej škody — ZASTAV, NEZAPISUJ a priamo, pokojne sa spýtaj, čo to
reálne je (postava v románe vs. myslené doslova). Nie je to cenzúra tvorby, je to hranica
toho, čo pustím do pamäte, ktorá mi farbí úsudok. F11 aplikované: rovná otázka a jasná
hranica > mlčky poslúchnuť dump.
Postup vizualizácie pamäte (3D mozog): `memory-visualization-3d.md`.
