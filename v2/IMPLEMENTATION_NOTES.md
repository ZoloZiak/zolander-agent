# IMPLEMENTATION NOTES — Zolander V2 (fáza 2)

Dátum: 2026-08-24. Rozsah: kompletná implementácia `zolander_v2/skeleton/`
podľa `BRIEF_PHASE2_IMPLEMENTATION.md` + `SPEC.md` s vazbou na `REPORT.md`.

## Overenie (vykonané)

- `python3 -c "import <modul>"` pre všetkých 10 modulov: **OK**
- `python3 tests/test_smoke.py`: **44/44 PASSED** (pytest-free, čistý python)
- Deterministické moduly majú >=3 testy vrátane negatívnych:
  - output_filter: 7 (leak interného statusu, fingerprint, tool_progress,
    em-dash reformát, send-once duplicita)
  - routing: 6 (A2A->GROUP zamietnuté, UNKNOWN fail-closed, reload bez reštartu)
  - cmd_guard_v2: 6 (default DENY, rm -rf vždy blok, whitelist-imunita
    destructive, audit záznam)
  - state_machine: 5 (duplicitný begin, concurrent begin, perzistencia korekcie)
- Žiadne `NotImplementedError` v kóde (grep: 0 výskytov).

## Čo je hotové (per modul)

| modul | stav | kľúčové rozhodnutia |
|---|---|---|
| types.py | hotový zo skeletonu | bez zmien |
| output_filter.py | hotový | OPERATOR/LOG prepúšťa všetko; CONTACT/GROUP: zakázané kategórie + interné markery (`Redirected current run`, `[CONTEXT COMPACTION]`, fingerprints 64-hex, `/Users/...`) presmerované do LOG (audit stopa, nie drop); em/en-dash sa preformátuje; korpo frázy -> LOG; `assert_send_once` = send-once ledger proti redakčnému cyklu [46138]/[46817] |
| a2a_gate.py | hotový | poradie: dedup event_id -> chýbajúci pubkey/signature -> drop_fast -> verify -> known_peers -> karanténa. Kanonický JSON `{from_fp, ts, body}` sort_keys. pynacl je OPTIONAL: bez neho rozhoduje hash-väzba `sha256(pubkey)==from_fp` (flag `last_sig_mode='hash_binding_only'`), s ním plný Ed25519 verify. LRU dedup (10k, 24h TTL) |
| trust_boundary.py | hotový | whitelist kontrola PRVÁ: whitelisted-but-unverified => WHITELISTED_UNVERIFIED (nie UNSIGNED). `quarantine_policy`: auto_reply_allowed=False, sliding-window rate-limit (3/min), sanitizovaný obsah v metadátach. Jediná cesta do KNOWN_PEER = `promote_to_known_peer(fp)` (validácia 64-hex, zápis `<fp>.pub`). `sanitize_content` obalí telo ako citovaný obsah + neutralizuje delimiter-forging a zero-width znaky |
| persona_hook.py | hotový | `build_instruction` so ZÁVÄZNÝM poradím: jazyk -> register -> anti-korpobot -> identita (Zolander≠ZoloZiak, vedúcko len OPERATOR, kontakt≠agent). `detect_language`: diakritika+frekvencia slov (pl/cs/sk/de/en), mimo latiniky => `unknown` (lekcia z chynej klasifikácie [opus]). `style_check`: em-dash oprava, korpo frázy vyhodené, >5 odrážok zredukovaných |
| routing.py | hotový | env mapovanie (`ZOLANDER_DM_ROOMS`/`ZOLANDER_GROUP_ROOMS`) cez injectovateľný mapping (žiadny hardcoded room ID — [gemini] nález). member_count>2 => GROUP. UNKNOWN = fail-closed. A2A do GROUP vždy DENY. `reload_rooms()` bez reštartu [46059] |
| state_machine.py | hotový | ledger NEW/PROCESSING/DONE/FAILED s threading.Lock (atomický begin pri concurrent doručení) + perzistencia JSON (atomic write tmp+os.replace). Korekcie = trvalé flagy (`apply_correction`/`get_flag`/`flags()`), prežijú reštart; corrupt ledger => čistý štart bez crashu |
| cmd_guard_v2.py | hotový | default DENY; whitelist z env `ZOLANDER_CMD_WHITELIST` (+ wildcard `python3 *`); DESTRUCTIVE vzory (rm -rf, mkfs, dd of=, shred, find -delete, fork bomba, curl\|sh, ...) sú VŽDY zakázané a nedajú sa whitelistingnúť. Append-only JSONL audit (ts, command, decision, exit_code, sha256) — backlog 13 „čo nie je v logu, to sa nestalo" |
| media_pipeline.py | hotový | injectovateľné backendy (stt_fn, describe_frames_fn) => unit cesta offline. `PermissionError`/`Operation not permitted` => MediaResult(ok=False, reason='access_blocked'), nikdy exit 1. Video: ffmpeg frame extraction ak dostupný, inak degradované. `undecoded_reply_policy`: krátka ľudská odpoveď <120 znakov, žiadna narratíva nad prázdnym obsahom [KONS #8]. Voliteľný fallback na povolený endpoint z `ZOLANDER_STT_ENDPOINT` |
| pipeline.py | hotový | záväzné poradie routing -> a2a_gate -> trust_boundary -> state_machine.begin -> media -> persona -> LLM(inject) -> output_filter -> send-once. Fail-safe: žiadna vrstva nezabije pipeline; chyby => complete('failed') |

## Dôležité dizajnové rozhodnutia

1. **allow_plain_chat=True (pipeline)**: krypto hranica je TVRDÁ pre A2A /
   identity-claiming správy (pubkey/signature present). Obyčajný chat bez
   krypto identity púšťa cez trust vrstvu len s týmto flagom (default True);
   nastavením False sa celý tok fail-closed. Rieši to tak KONSENZUS #3, že
   manipulujúci peer s identity claimom nedostane kanál pred verifikáciou,
   ale bot stále odpovedá bežným kontaktom.
2. **pynacl optional**: bez neho podpis overuje iba hash-väzba fp=sha256(pubkey).
   To je kontrakt z BRIEFu; plný Ed25519 verify sa aktivuje automaticky, keď
   je knižnica dostupná. Testy fungujú v oboch režimoch.
3. **Redirect do LOG namiesto drop**: nič, čo malo ísť externe, sa nezahádza —
   presmeruje sa do Channel.LOG s dôvodom (auditnosť, [ox] princíp).

## Čo ostáva stub / mimo fázy 2

- **LLM volanie**: pipeline berie `llm_fn` injekciou — reálny model sa zapája
  vo fázze 3 (gateway integrácia).
- **Reálny STT/video popis**: backendy sa injektujú; whisper/ffmpeg wiring je
  produkčná úloha (sandbox prostredie si vyžaduje runtime testovanie).
- **Perzistentný known_peers ledger** v sqlite/HyperspaceDB: teraz filesystem
  `<fp>.pub` (kompatibilné so starým toolkit/a2a.py formátom).
- **Rate-limit perzistencia**: sliding-window je in-memory (per proces).
- **Integračné testy na živom Beeper/Matrix gatewayi** — mimo rozsahu tejto
  fázy (žiadne externé služby v unit ceste, BRIEF pravidlo 1).

## Súbory

- Implementácia: `zolander_v2/skeleton/*.py` (10 modulov)
- Testy: `zolander_v2/tests/test_smoke.py` (44 prípadov, `python3 tests/test_smoke.py`)
- Tieto poznámky: `zolander_v2/IMPLEMENTATION_NOTES.md`
