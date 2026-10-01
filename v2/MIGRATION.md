# Zolander V2 — MIGRATION zo starého toolkit/

Zdroj: `~/projects/zolander/toolkit/` (živý kód — tu sa NEdotýkame, len sa na
ňho odkazujeme). Audit (VERDIKT) konštatoval: „Rozhodovacie jadro funguje;
zlyhania sú lokalizované v štyroch vrstvách… Odporúčam cielenú iteráciu."
Preto migrácia nie je 1:1 presun: **čo funguje, preberáme; čo je deravé,
prepisujeme; čo patrí inej vrstve, zahadzujeme.**

## PRESÚVA SA (preberá sa logika, adaptuje na V2 typy)

| starý súbor | kam vo V2 | poznámka |
|---|---|---|
| `toolkit/a2a.py` | `skeleton/a2a_gate.py` | Kanonický podpis (JSON {from_fp, ts, body}, sort_keys), formát `known_peers/<fp>.pub`, Ed25519 verify — preberá sa 1:1. NOVÉ: drop-fast + dedup pred akoukoľvek analýzou (KONSENZUS #5). |
| `toolkit/gen_identity.py` | identity layer (mimo skeletonu) | PEM PKCS8 kľúč + fingerprint.txt; ostáva, len prísnejšie umiestnenie a `.gitignore`. |
| `toolkit/hook_matrix_persona.py` | `skeleton/persona_hook.py` | Idea (persona kontext per-kanál) ostáva; PREPÍSANIE obsahu inštrukcií: jazyk-mirror ako PRVÁ inštrukcia, anti-korpobot, identita Zolander ≠ ZoloZiak (KONSENZUS #6). |
| `toolkit/hook_cmd_guard.py` | `skeleton/cmd_guard_v2.py` | Hook mechanika ostáva; PREPIS: blacklist → whitelist (backlog 11) + audit log s exit kódmi/hashmi (backlog 13). |
| `toolkit/zol_session.py`, `toolkit/zol_events.py` | `skeleton/state_machine.py` | Stav eventov sa presúva do idempotentného ledgeru s perzistenciou (KONSENZUS #4). |
| `toolkit/hook_recall.py`, `toolkit/mem_*` (výber) | pamäťová vrstva (fáza 2) | Nechádza sa tak ako je; V2 ju len volá cez state_machine flagy. |
| `toolkit/zol_paths.py` | zdieľané paths util | Bez zmeny konceptu. |

## PREPISUJE SA (nový modul, starý kód nezostáva)

- **Display/output vrstva** → `output_filter.py`. Starý systém nemal žiadny
  jednotný výstupný bod — tool-progress, thinking tokens a interné statusy
  išli priamo do DM [46813:L4189/L4210/L4418]. Nové: jediná brána
  `filter()` + send-once (`assert_send_once`) namiesto send-then-redact
  ([46138]/[46817]).
- **Trust poradie** → `trust_boundary.py`. Starý flow spúšťal auto-reply hneď
  po whiteliste (reštart 18:16), verifikácia prišla o ~40 min neskôr
  [46052 vs 47527]. Nové: karanténny stav `WHITELISTED_UNVERIFIED`,
  auto-reply zamknutá do `promote_to_known_peer()` operátorom.
- **Routing** → `routing.py`. Manuálna dedukcia DM/group v agentovom texte
  [46042] sa ruší; klasifikácia ide do infra s fail-closed UNKNOWN=GROUP.
- **STT/video handling** → `media_pipeline.py`. Starý kód padal na sandbox bloku
  (`Operation not permitted`, exit 1) a video posielal ako placeholder.
  Nové: degradovaný MediaResult + fallbacky (quick-win 4).
- **Whitelist management** (`set_whitelist.py`, `matrix_whitelist_backup_16.txt`)
  → dynamické mapovanie z env + `reload_rooms()` bez reštartu (unikátny nález
  [gemini] č. 10).

## ZAHADZUJE SA

- **Send-then-redact správanie** celkom — žiadna odpoveď sa neposiela „na skúšku".
- **Manuálne záložné whitelist súbory** (`matrix_whitelist_backup_16.txt`) —
  nahradené env/konfiguráciou s verziovaním.
- **Hardcodované room ID / tokeny v kóde** — len env placeholdery
  (`MATRIX_ACCESS_TOKEN`, …); `.gitignore` pravidlá pre secrets (backlog 15).
- **Blacklist cmd_guard logika** (`rm -rf` ako jediná obrana) — nekonvertuje sa,
  píše sa od nuly whitelist.
- **Narratívne dlhé odpovede na prázdny vstup** — žiadne „fallback romány";
  undecoded médium = krátka odpoveď alebo ticho.
- **NEROBIŤ položky z REPORT.md sekcie (c)**: cloud/dedik server pre chatové
  dáta (sandbox konflikt), fake proof-of-consciousness hash ako identita,
  „sken = pečiatka" pattern.

## PORADIE IMPLEMENTÁCIE (navrhnuté podľa priorit REPORT.md backlogu (b))

1. trust_boundary + routing (priorita 4/3, KONSENZUS #3/#9)
2. state_machine (dedup + corrections, priorita 4)
3. output_filter + send-once (najviditeľnejšia oprava, quick-win 1+5)
4. a2a_gate drop-fast (quick-win 2)
5. persona_hook (register mirroring)
6. cmd_guard_v2 whitelist + media_pipeline fallbacky

## Overenie skeletonu

```
cd zolander-refactor
for m in types output_filter a2a_gate trust_boundary persona_hook \
         routing state_machine cmd_guard_v2 media_pipeline pipeline; do
  python3 -c "import zolander_v2.skeleton.$m"
done   # všetkých 10 modulov importuje OK (overené 2026-08-24)
```

---

# DEPLOY PLÁN (finálny, 2026-08-25)

## Overený stav kódu
- **77/77 testov PASS** vo `.venv` (pynacl 1.6.2, skutočný Ed25519 režim) —
  overené nezávislým behom, nie self-report.
- Všetky podmienky z REVALIDATION_REPORT.md splnené: pynacl tvrdá závislosť,
  f1 test beží v reálnom režime (ukradnutý pubkey = drop), cmd_guard -c/-m +
  basename normalizácia, guard_outbound zapojený (A2A→GROUP DENY,
  legitímne GROUP replies prechádzajú).
- Re-validácia (3 readery + judge): všetkých 8 dier zatvorených.

## Postup nasadenia (keď vedúcko schváli)
1. **NEVYMAŇOVAŤ za živý beh.** Starý toolkit ostáva funkčný paralelne.
2. **Shadow mód** (odporúčaný prvý krok): v2 pipeline beží na kópiu inbound
   eventov, jej rozhodnutia sa len LOGUJÚ (drop/allow), nič sa reálne neposiela.
   Bež 2–3 dni, porovnaj logy v1 vs v2.
3. **Postupné prepínanie modulov** v poradí: routing → output_filter →
   a2a_gate → trust_boundary → state_machine → cmd_guard_v2 → persona_hook →
   media_pipeline. Po každom: deň pozorovania.
4. **Rollback**: každý modul má env-vypínač; stará cesta ostáva nedotknutá
   dovtedy, kým nie sú VŠETKY moduly v produkcii 3 dni bez incidentu.

## Známe hranice (poctivo)
- **Latencia/api_calls (KONS #7)** — mimo dosahu architektúry (model limit).
- **STT sandbox blok (KONS #10)** — pipeline nezpadne, ale STT funkcionalita sa
  nevrátila; audio zostáva „nedostupné" flag.
- **DM s bridge-botom (members=3)** — klasifikuje sa ako GROUP, A2A tam musí mať
  explicitný env záznam (fail-closed trade-off, dokumentované v replay #39).
- **persona register mirroring** — mechanické chyby (em-dash, korpo frázy) rieši
  kód; jemný sociálny register ostáva na LLM + system prompte.

