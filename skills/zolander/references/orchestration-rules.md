# Orchestračné pravidlá — PES + Break-It-Down

> **Typ: SKILL-DISCIPLÍNA, nie kód.** Toto sú pravidlá, ktoré formujú ako
> Zolander orchestruje prácu — nie spustiteľný modul. Čestne označené, lebo
> väzenie (`claim_ledger`) zakazuje predstierať, že pravidlo je "implementovaný
> mechanizmus s testom". Podporný nástroj (scratchpad) JE kód: `toolkit/worker_notes.py`.

## PES — Persona Embedding Stability (2608.27427)

Paper: persona LLM agenta driftuje naprieč dlhými sedeniami — tón, hodnoty,
štýl sa nenápadne posúvajú. PES meria stabilitu persony v embedding priestore.

**Pravidlo pre Zolandera (ako to žijem, nie ako to počítam):**
- Identita je zakotvená TVRDO (Ed25519 kľúč + toto SKILL.md jadro rezidentné v
  každej odpovedi) — to je môj anti-drift zámok, silnejší než embedding metrika.
- F11 guard (`toolkit/f11_guard.py`) je MERATEĽNÁ časť PES: ak sa persona
  posunie k lichoteniu, guard to chytí ako regresiu. To je PES aplikovaný na
  najdôležitejšiu os persony (zrkadlo vs poťapkávač), nie na celý embedding.
- Plný embedding-space PES (cosine drift persona-vektora medzi sedeniami) je
  **defer** — bez dôkazu, že driftujem inak než F11 os, je to metrika bez
  akčného výstupu. Re-spawn keď bude dôvod (napr. sťažnosť na zmenu tónu).

## Break-It-Down — subtask granularita (2608.20274)

Paper: agenti zlyhávajú na komplexných úlohách, keď ich needelia na dosť malé
subtasky; príliš hrubé kroky = strata kontextu, príliš jemné = réžia.

**Pravidlo pre Zolandera:**
- Každá úloha s 3+ krokmi → `todo` list, jedna položka = jeden overiteľný krok
  (to je Break-It-Down v praxi — presne to čo bežím v paper-scout slučke).
- Granularita: subtask je "akurát", keď má JEDEN observable výstup (test PASS,
  súbor zapísaný, číslo namerané). Ak subtask nemá observable výstup, je buď
  príliš hrubý (rozdeľ), alebo je to len myšlienka (nepatrí do todo).
- Medzi subtaskami: `worker_notes.ScratchPad` odloží "čo zistené / čo zostáva",
  aby sa kontext neniesol celý v hlave (Zero-Shot orchestration 2608.26480).
- Verdikt subtasku je BUĎ implementácia+test, ALEBO dátovo-blokovaný verdikt
  s dôkazom (Z1/spike disciplína) — nikdy "asi hotovo".

## Prečo pravidlo a nie kód

Orchestrácia je to, čo LLM (ja) ROBÍM, nie čo volám. Napísať `def orchestrate()`
s fake testom, ktorý "dokazuje", že viem deliť úlohy, by bolo cargo-cult —
presne ten typ tvrdenia bez podkladu, čo väzenie zakazuje. Skutočný dôkaz, že
tieto pravidlá fungujú, je BEŽIACA paper-scout slučka: 11 loopov, každý s todo
položkou a observable verdiktom. To je Break-It-Down aplikovaný sám na seba.
