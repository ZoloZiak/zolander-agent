# OPENCODE_PORT.md — Zolander na opencode, faz 1

> Zolander pôvodne bezal na [Hermes Agent](https://hermes-agent.nousresearch.com) (macOS).
> Toto je jeho port na **opencode** (Windows) s modelom **`opencode/glm-5.3-flash-free`**
> (zadarmo v opencode; mimo opencode je endpoint `opencode.ai/inference/...` rate-limitovany 429, overené 2026-10-26).
> Stejná poctivosť ako v README: rozdelenie co BEZI a co je ROADMAP. Bez green-checku sa
> tvrdenie nedostane do tejto sekcie.

## Co bezi dnes (green-checks)

- **Persona ako opencode agent.** `.opencode/agents/zolander.md` (mode: primary,
  model `opencode/glm-5.3-flash-free`) + `.opencode/opencode.json`
  (`default_agent: zolander`, permissions).
  *Zdroj:* harness skill-list ukazuje skill `zolander` — discovery funguje.
- **Recall-first (port hermes `pre_llm_call` hook).**
  `.opencode/plugins/zolander/index.js` — opencode session hook `prompt`: raz na
  prvú správu session vstrieka `[Zolander auto-recall...]` (chvost `state/PLAN.md`
  + posledné zapisy `state/zol_memory.jsonl`), fail-open, bez DB/embeddera.
- **Hard foundation do systému (anti-drift).** Ten istý plugin — session hook
  `context` pushuje do systemového kontextu krátký F11/sandbox/honesty blok
  (port hermes myšlienky "data injection belongs in hooks", nie v prose).
- **Mechanická anti-halucinácia/anti-sycophancy brána.** Bez zmeny, pôvodný
  `toolkit/zol_guard.py` (stdlib, bez LLM) pracuje aj na Windows.
  *Green-check:* `python toolkit/zol_guard.py` vypise rezimy (overené rucne,
  exit 2 bez argmentu a bez LLM); `verify-*` volania idú na skutocné subory.
- **Double-take brána (jadro).** Nový mode `echo '{"problem":...}' | python
  toolkit/lens.py gate-classify` — čisto deterministický klasifikátor bez LLM.
  Port-rozdiel: `lift` robí agent sám (vlastná revizia), NIE Opus cez hermes.
  *Green-check:* serious otázka skore 3 → `double_take: true`; trivialná skore 0
  → `false` (overené 2026-10-26 na Windowse).
- **Light pamat L0.** `toolkit/mem_light.py` (nový, stdlib) →
  `state/zol_memory.jsonl`; lexikalny recall (keyword prekryv + recencia),
  schema kompatibilná so zol_mem (kind/layer/salience/confidence).
  *Green-check:* `python toolkit/mem_light.py remember --text "..."` potom
  `... recall --query "..."` — hit s score (overené 2026-10-26: score 4.95).
- **Mechanické bezpečie.** `permissions` v `.opencode/opencode.json`: shell `ask`
  default, git read allow, `rm -rf` / `force-push` deny, external dir `ask`.
  (Tvrdý zámok v configu, nie v prose.)

## Roadmap (NIE je implementované — o tom to celé nie je)

1. **Hyperbolická pamat L0–L3 (YAR v5 + HyperspaceDB, dream, ascend).** Závisí na
   torch embedderi (~2-3 GB) + HyperspaceDB (Docker) na Windowse. `mem_light.py`
   je jeho L0-predchodenec; migrácia re-embedne texty (vektory nečitatelné
   rovno, rovnako ako v pôvodnom memory-backup-migrácii).
2. **Cron daemony (loop/dream/brief/watchdog/notify).** Hermes launchd/systemd →
   Windows Scheduled Tasks. Dnes NIE (odhad: ~1 deň práce, ale bez testu to niet).
3. **MoA cross-model review** (opt-in analóg `ZOL_VERIFY_MOA` z hook_verify).
4. **A2A Ed25519 podpis** nad light pamatou (`toolkit/a2a.py` existuje a bezi,
   nepripojený v porte; kľúč sa generuje ako doteraz cez gen_identity.py).
5. **STT (slovenský Whisper), Matrix/WhatsApp gateway, Palantir, macOS banner** —
   neportované; väčšina závisí na prostredie (korporát/macOS), nie na porte.

## Model poctivost (overené 2026-10-26)

- `opencode/glm-5.3-flash-free` — v opencode zadarmo (čísla: input/output/cache 0).
- Priame volanie `https://opencode.ai/inference/openai/v1/chat/completions`
  z externého klienta bez kľúča: funguje po limit (`429 FreeUsageLimitError`,
  "Free models work in OpenCode"). Ked teda beží niečo mimo opencode, musí to
  byt platena cesta (OpenCode Go subscription / OpenRouter / klic) alebo sa cakat na reset.
- Variants: low/high/max (reasoning effort) — default je bez variantu.

## Rýchly test po inštalácii

```
python toolkit/mem_light.py recall --query "port"   # pamat: {"ok": true, hits}
python toolkit/zol_guard.py                          # vypise rezimy + exit 2
```
Opencode v tomto repu: otvor session s agentom `zolander` (`/agents` alebo
default) — prva sprava dostane `[Zolander auto-recall...]` blok.
