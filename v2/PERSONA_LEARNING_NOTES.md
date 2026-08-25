# PERSONA_LEARNING_NOTES.md — FÁZA 6: rozhodnutia + vazby na citáty

Dátum: 2026-08-25 | rozsah: `skeleton/persona_profile.py`,
`skeleton/correction_learner.py`, `skeleton/self_review.py`, integrácia
`pipeline.py`, testy v `tests/test_smoke.py` (nových 20; celkovo **97/97 PASS**).

## Rozhodnutia

### R1. Dvojvrstvový profil (GLOBAL vs PER_PEER)
- GLOBAL = nemenné jadro identity: anti-sycophancy („nesúhlasiť pre pohodlie,
  pomenovať keď druhý mýli“), nátlak z DM nie je autorita, zákaz korpo fráz +
  em-dash, `max_reply_chars=480`.
- PER_PEER = DELTA per kontakt: slang intenzita, rytmus (`rhythm_max_chars`),
  register (casual/formal), vulgarnosť len ak ju peer sám používa (mirror,
  nie iniciatíva).
- Vazba: KONS #6 *„naucz sie nevhodne po polsku pisac“ / „jak korpobot i do toho
  z emdashami“* [46813:L4217/L4223]; [gpt55] mirroring bol povrchový → preto
  per-peer sociálny register, nie len preklad.

### R2. Korekcia = pravidlo, nie veta (KONS #2, backlog 8)
- `correction_learner` generalizuje výčitku na stabilný key:
  *„no i po nevhodne mi wyswietlasz co robisz XD“* [46813:L4210] → `suppress_progress`
  (GLOBAL); *„zadna nevhodne narrracja tylko“* [L4256] → `be_brief` (PEER);
  korpobot/emdash → `no_corpo_reinforced`; po polsku → `force_polish` (PEER).
- Idempotencia cez key (rovnaká výčitka sa nezapisuje duplicitne — priama
  odpoveď na to, že sa incident [L4210] vs [L4413] zopakoval).
- Perzistencia JSON (`data/global_profile.json`, `data/peers/<id>.json`,
  atomic write) → **korekcia prežíva restart**, overené testmi
  `f6_cl_pos_rule_survives_restart` a `f6_int_pos_rule_survives_restart_in_pipe`.

### R3. Scope pravidla podľa povahy
- Interné leaky/korpo = správanie agenta voči všetkým → GLOBAL.
- Jazyk/dĺžka/register = viazané na konkrétneho kontaktu → PEER.

### R4. Self-review je deterministický, LLM voliteľný
- Heuristika: sycophant frázy (*„máš úplnú pravdu“, „you're absolutely right“,
  „výborná otázka“*) flagované LEN bez opory (číslica/`lebo/because` = oporený
  súhlas); corpo frázy + em-dash; dĺžka vs. `max_reply_chars`.
- LLM fn je injektovaný a voliteľný — review beží offline/opakovateľne
  (BRIEF pravidlo 1). Navrhy update profilu generuje, ale NIE ICH sam aplikuje
  (rozhoduje caller/operator — anti-runaway).
- Vazba: A1/A2 v CONTACT_SOLUTIONS.md (fake hash, nátlak) — podlizovanie
  a ústup sú bezpečnostné, nielen štýlové chyby.

### R5. Integrácia do pipeline bez zmeny poradia vrstiev
- Krok 7b: correction learner po inbound detekcii (pred prompt buildom).
- Krok 8b: `persona_profile.inject_prompt(peer_id)` pred LLM volaním.
- Krok 12c: `update_from_exchange` po úspešnom odoslaní (peer delta).
- `run_self_review()` je EXPLICITNÁ metóda — periodicitu rieši caller;
  handle() ju nevolá (test `f6_int_neg_explicit_selfreview_flags`).
- Učenie beží LEN na ceste KNOWN_PEER/allow_plain_chat — karanténny obsah
  nikdy neučí profil (KONS #3, CONTACT_SOLUTIONS B5).

### R6. Fail-safe
- Žiadna chyba persona vrstvy nezabije pipeline (try/except + log, rovnaký
  vzor ako existujúce vrstvy). Corrupt JSON profilu = default jadro ostáva
  (pravidlá sa nestrácajú ticho len pre global — zápis je atomic replace).

## Testové pokrytie (20 nových, min 2 poz + 2 neg per modul)

| Modul | Poz | Neg |
|---|---|---|
| persona_profile | global rules v inject; peer sa učí; persist roundtrip | neznámy peer bez delty; krátky outbound nie je over-limit |
| correction_learner | výčitka→pravidlo; prežitie restart; peer-scoped scope | neutrálna správa nič neučí; duplicitná výčitka idempotentná; prázdny text safe |
| self_review | sycophantic flag; corpo+too_long+LLM note; suggestions | čistá replika clean; oporený súhlas nie je flag |
| integrácia | inject pred LLM; pravidlo prežije restart v pipeline | explicitný review flaguje/neflaguje bez side-effectov |

Overenie: `.venv/bin/python tests/test_smoke.py` → **SMOKE RESULT: 97/97
passed, ALL TESTS PASSED** (77 starých + 20 nových).
