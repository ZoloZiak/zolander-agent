# Abstrakčný stroj (§11) — ako EMPIRICKY otestovať PRED stavaním (overené 2026-08-10)

Pravidlo vedúcka "testy pred rozhodovaním": NEstavaj generatívnu slučku (Fréchet mean →
LLM pomenuje princíp) kým geometria REÁLNE nesie abstrakciu na TVOJICH dátach. Dva lacné
deterministické testy to rozhodnú za pár minút — spusti ich, až potom sa rozhoduj.

## TEST 1 — r-distribúcia per layer (jadro tézy "r nesie abstraktnosť")
Ak téza platí, abstraktné (L2/L3) uzly majú MENŠÍ polomer než konkrétne (L0).
Recept: čítaj mem_index.jsonl (má layer+text; getPoints má server bug, tak re-embed),
pre každý layer spočítaj r = math.acosh(x0) z YAR vektora (v[0]=x0), porovnaj r_mean.
Interpretácia:
- L2 r výrazne < L0 r (rozdiel > 1 sd) → PODPORENÉ.
- rozdiel < 1 sd L0, alebo n(L2) je pár uzlov → NÁZNAK nie dôkaz (nepredávaj ako výhru).
- L2 r > L0 r → VYVRÁTENÉ (opak očakávania).

## TEST 2 — kalibračný sweep prahov (má dátová sada vôbec klastrovú štruktúru?)
Greedy cluster cez lorentz_dist pri prahoch 1.0 … 6.0, počítaj koľko vznikne klastrov
>=3 členov. Hľadáš prah so 3-8 zmysluplnými klastrami.
- Ak KAŽDÝ prah dá buď prach (N úlomkov) alebo jednu guľu (všetko v 1) a žiaden sweet
  spot → dáta NEMAJÚ klastrovú štruktúru → abstrakčný stroj nemá surovinu.

## KRITICKÁ DISCIPLÍNA — kedy NEspustiť LLM pomenovanie
Ak Test 2 nenašiel zmysluplné klastre, NESPÚŠŤAJ Opus na pomenovanie "spoločného
princípu". Na štruktúrovanej-menej skupine LLM vždy vygeneruje hlbokoznejúci ale PRÁZDNY
pseudo-princíp (red-team obava #1 = "rakovinový L3 axióm"). Spustiť = klamať seba, aby
čísla vyzerali lepšie. Radšej povedz "nefunguje" než ukáž falošný pekný výstup.

## VÝSLEDOK 2026-08-10 (263 faktov)
Test 1: L0 r=1.3786 (sd 0.074) vs L2 r=1.3226 (n=4) → smer sedí, dôkaz slabý.
Test 2: prah 1.0 = 70 úlomkov, prah 1.5+ = jedna guľa (242-263) → ŽIADNA štruktúra.
Príčina: pamäť ~90% homogénny tech-stack (writeback z coding session), YAR ich dal do
úzkeho pásu r≈1.38 lebo sú si sémanticky podobné.
ZÁVER: NEstavať teraz. Re-test keď (a) pamäť zpestrie o nie-tech fakty, (b) je desiatky
L2/L3 uzlov. Ak ani potom → readout hlava (§11 fallback b) alebo prijať že YAR je RAG
index, nie abstrakčný rebrík. Koncept NIE je vyvrátený (Nickel&Kiela/HyperGuide ho
podložili), len na týchto dátach nemá surovinu — mlyn pri vyschnutom potoku.

## VÝSLEDOK 2026-08-29 (516 faktov, RE-TEST — splnené obe podmienky a+b)
Korpus dozrel: 516 záznamov, L0=302 L1=125 L2=61 L3=28 (desiatky L2/L3 = podmienka b OK),
zpestrený o nie-tech fakty (podmienka a OK). Re-test rozhodol OPAČNE než dúfal koncept:
Test 1: r-gradient TERAZ monotónny L0 1.379 → L1 1.378 → L2 1.366 → L3 1.292; L0-L3 = +1.20 sd
  → smer PODPORENÝ (silnejšie než 2026-08-10), ALE celý korpus v úzkom páse r 1.29-1.38,
  distribúcie sa masívne prekrývajú → r NIE je čistý separátor.
Test 2: prah 1.0 = 58 klastrov >=3, ostrý prechod do jednej gule pri 1.5 → štruktúra UŽ JE
  (na rozdiel od 2026-08-10 vyschnutého potoka).
NOVÝ Test 3 (cone-veto, Ganea 2018): cone AUROC 0.692 < obyčajná Lorentz distance 0.742 →
  cone-veto PREHRAL s baseline čo máme zadarmo. K-sweep 0.1-1.5: parent-hrany v kuželi 0.0-0.3%.
  Parent rešpektuje r len v 49% (hod mincou) → hrany asociatívne, nie hierarchické.
DECÍZNY Test 4 (abstraction ladder 5×5, SK+EN): radiálny rozsah 25 extrém textov = 0.401 ≈
  516 reálnych 0.433 → strop je VLASTNOSŤ EMBEDDERA, nie objem dát. Kŕmenie ho nerozšíri.
  SK 11/16 = EN 11/16 identicky → slovenčina NIE vinník (EN len ~20% širší rozsah).
KOREŇOVÁ PRÍČINA (tretia možnosť, ani hlad ani plocho): YAR stláča radiálny dynamický rozsah
  do ~0.4 pásu nech dostane čokoľvek. "Existencia" (najabstraktnejšie) sa dostane len na r≈1.07,
  nikdy k origine → absolútne kužele nemajú kde stáť (rodič musí byť pri r→0).
ZÁVER 2026-08-29: absolútna hyperbolická HIERARCHIA (cone-subsumption ako runtime veto) na
  tomto embedderi NEFUNGUJE a lacnejší distance-veto ju porazí. NEstavať cone-veto.
  PREŽÍVA a ostáva užitočné: (a) tematické zhluky (58), (b) episodická trajektória,
  (c) vnútro-klastrové RELATÍVNE r-poradie. Retrieval ostáva BM25/dense (0.83 vs 0.38).
  Oprava steny = iný/dotrénovaný embedder = zamietnuté strategicky (RFC §7e: nesprávna páka).
  Plný spike: docs/geometry-rethink-RFC.md §7c/7d.

## Znovupoužiteľné skripty (písané ad-hoc, vzor)
r-dist: re-embed textov per layer → math.acosh(v[0]) → r_mean/sd/rozsah + verdikt.
sweep: embed raz do /tmp cache → cluster() pri prahoch → počet klastrov>=3 per prah.
Oba /Users/__USER__/zolander/.venv-yar/bin/python (YAR torch), fail-open na parse.
