# Pamäť ako "kalkul asociácií" — poznatky z DDA paper (2026-08-14)

Zdroj: Chris Royse, "The Calculus of Association: A Formula for Artificial General
Intelligence" (preprint, 3 jún 2026, Leapable.ai / socialmedia2.com). Prečítané celé
(18 strán) keď vedúcko poslal `~/Downloads/FormulaForAGI.pdf` a spýtal sa "vieme to využiť?".

## Prečo je to relevantné pre Zolanderovu pamäť
Náš hybrid recall (YAR + BM25 + re-rank, viď SKILL.md sekcia HYBRID/RECALL v3/EVAL) je
nezávisle postavená **zmenšená verzia presne tohto rámca**. Paper dáva slovník a teóriu
pre to, čo sme empiricky nahmatali — a tri konkrétne posuny navyše.

## Jadro tézy (bez hype)
- Inteligencia = meranie + počítanie + rozlišovanie + skladanie ASOCIÁCIÍ, ukotvených
  v reálnom výstupe. Slovník nedefinuje slovo slovom (Harnadov symbol grounding) — význam
  nesú VZŤAHY medzi slovami, nie slová. ~99% definovateľné z ~1% "grounding kernel".
- **Zamrznutý embedder = merací prístroj, nie vektorizér.** Neukladá dáta, ukladá geometriu
  vzťahov v korpuse. Nový vstup ním "premeriaš" → jeho súradnica vo webe asociácií.
  (= presne náš YAR: zmrazený, deterministický, reportuje polohu.)
- **Lens je vyrobiteľný**: aký korpus zmrazíš, taký merací prístroj dostaneš. Panel N
  prístrojov = navrhnuteľná báza pre význam.

## Tri konštrukty
1. **Derived Data Abundance (DDA)**: n vstupov cez N approx-nezávislých prístrojov →
   n·(N + C(N,2) + 1) štruktúrovaných signálov. Tie C(N,2) **cross-terms** (asociácie medzi
   asociáciami) sú tam, kde býva význam. POZOR: je to HORNÝ odhad pod approx-nezávislosťou;
   reálny zisk = "effective rank" << nominálne N (embeddery na prekrývajúcich korpusoch
   korelujú). Data-processing inequality: panel NEMÔŽE mať viac info o reálnom výstupe než
   surový korpus — DDA len re-exponuje latentnú štruktúru, hlavný benefit = nižšia
   sample-complexity.
2. **Meaning compression**: yield štruktúrovaných signálov na vstup (nie redukcia bitov).
3. **Teleological Constellation Training (TCT)**: ten istý zmrazený panel ako retriever +
   labeller + runtime guard (Gτ, per-output kosínusový prah). = analóg nášho re-ranku/guardu.

## Definícia = konštelácia, nie bod (najdôležitejšia myšlienka pre nás)
Jeden prístroj dá len INDEX (súradnicu). Význam = konštelácia, ktorú ostatné prístroje
ukážu na tom indexe + charakteristické cross-korelácie medzi nimi. "Happy" nie je bod
v affect-space ale cross-space podpis (affect↔prozódia↔vizuál). Marginály sú znaky,
cross-terms sú význam.

## GROUNDING — najtvrdší bod, priama lekcia pre našu pamäť
Asociácie bez kotvy = Harnadov nekonečný slovník-kolotoč ("veľmi efektívny spôsob ako
počítať nič"). Escape = kotva v REÁLNOM ne-lingvistickom výstupe (Docker pass/fail,
nahraný speaker, 30-dňové stretnutie). NAŠA pamäť teraz kotvu NEMÁ — spomienky sú texty
bez naviazania na "fungovalo to / bola rada správna". Hlbšia myšlienka: viazať
salience/confidence na reálny výsledok → pamäť prestane byť archív, stane sa uzemnená.

## Tri konkrétne posuny pre nás (od najlacnejšieho)
1. **Differentiation contract v BITOCH** (ich D1/D2): každý lens musí pridať ≥0.05 bitu info
   o reálnom výstupe; žiadny pár nesmie korelovať >0.6, inak vyhoď. TOTO je metrika ktorá
   kvantifikuje otázku čo eval nechal otvorenú: "oplatí sa YAR držať popri BM25?" (eval
   ukázal že pridáva málo — kontrakt by to zmeral v bitoch a rozhodol). Dorobiteľné do
   mem_eval.py (mutual-information gain per zdroj).
2. **Cross-term ako signál**: teraz kombinujeme YAR+BM25 skóre lineárne. Vzťah medzi
   "kde leží v YAR" a "kde v BM25" je SÁM signál — záznam vysoký v OBOCH je iný typ trefy
   než vysoký len v jednom. Mohlo by zdvihnúť R@1 nad 0.83.
3. **Grounding salience** (viď vyššie).

## Kritické ohraničenie (F11 — nie hype)
- Preprint od zakladateľa dvoch firiem čo na tom stavajú produkt (priznaný competing interest).
  NIE peer-reviewed breakthrough — dobre napísaná syntéza existujúcich vecí (multi-view
  learning Blum&Mitchell, Gärdenfors, symbol grounding) + firemné systémy ako dôkaz.
  Sami píšu: "architektúra hotová, meranie prebieha... vzorec, nie hotový dôkaz."
- Ich čísla (92 signálov/vstup) sú horný odhad, reálne oveľa nižšie.
- Použiteľná pre nás je KONCEPČNÁ časť (panel + cross-terms + differentiation + grounding),
  nie ich konkrétne systémy — nemáme 13 embedderov ani firemný korpus.

## Empirické potvrdenie ich tézy naším evalom
Náš eval (24 parafráz, 318 záznamov) je lokálny dôkaz ich hlavného tvrdenia "jeden lens
nestačí": yar_only R@1=0.38, +BM25 (2-lens panel) =0.83, +re-rank (guard) =0.92. Presne
ich "hodnota je v skladaní viacerých ukotvených prístrojov, nie v jednom".
