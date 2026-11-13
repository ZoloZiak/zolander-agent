# Zolander Agent

Persistent companion layer for [Hermes Agent](https://hermes-agent.nousresearch.com) with a stable identity across models, decaying long-term memory, and deterministic shell hooks that enforce mechanical rules outside the LLM.

This repo holds the agent itself: identity files, memory store, and the hooks that gate its turns. Side tools and one-off experiments built *with* the agent live separately in `zolander-extras`.

Personal project running on my own machines, published for anyone curious about the setup. Most of the work went into one question: which rules can you enforce mechanically in code, and which ones still depend on a prompt?

## Testing rule

A feature only goes into this README once a test exercises it against the real code. Anything untested stays on the roadmap.

- `toolkit/run_tests.py` runs 32 checks: 29 deterministic (no LLM, no network) and 3 live checks against a real model and embedder.
- Ideas borrowed from papers are tested before I rely on them. Each paper-backed mechanism carries its arXiv ID in the table under Memory.
- Concurrency tests spawn separate OS processes because the CLI and the gateway hit the store at the same time in real use. An early single-process thread test passed while 12 parallel processes silently dropped 5 of 12 writes; wrapping the full read-modify-write cycle in a file lock brought it to 20/20.
- Negative results stay in the repo. The geometric memory idea that started the project failed its own benchmark and is recorded below.

Current offline state on a clean Linux/WSL clone: **27 pass, 2 fail, 3 live skipped.** Both failures are known: `test_claim_ledger` expects local memory fixtures that aren't tracked in git, and one leak-gate assertion in `test_meta` is currently red.

```bash
python3 toolkit/run_tests.py --offline   # deterministic, no LLM, no network
python3 toolkit/run_tests.py             # includes live tests (needs LLM + embedder)
```

## Hooks and gates

System-prompt instructions ("don't chain shell commands", "recall before answering", "don't claim done if a file fails to parse") hold up until a long context window or a weaker model drops them. Whenever a rule has a mechanical test, Zolander runs it in a Hermes shell hook outside the model:

| Hook | Event | What it enforces |
|---|---|---|
| `hook_cmd_guard.py` | `pre_tool_call` | Blocks `rm -rf`, command chaining, `bash -c`, heredocs, and direct pushes to `main` before the shell sees them. |
| `hook_verify.py` | `pre_verify` | Stops the agent from ending a turn while an edited file fails syntax checks. Bounded and fail-open, with an optional second pass where two other models review the diff. |
| `hook_recall.py` | `pre_llm_call` | Injects relevant memories on the first turn of every session automatically, tagged as reference data rather than instructions. |
| `hook_skill_matcher.py` | `pre_llm_call` | Suggests skills deterministically from keywords and a curated trigger map. |
| `hook_env_guard.py` | `pre_tool_call` | Protects environment and config files from silent edits. |

Data injection and mechanical checks live in hooks; judgment and tone stay in the prompt. Wrapping a fuzzy property like "this code is thread-safe" in a regex gate only creates false confidence.

LLM-free check modules called by the hooks and CLI:

- `zol_guard.py`: flags confabulation phrasing, sycophancy markers, and uncited claims, and checks file/line/symbol references against disk.
- `claim_ledger.py`: keeps the turn gate closed if any recorded claim is refuted or left unverified.
- `f11_guard.py`, `scaffold_gate.py`, `lens.py`: anti-sycophancy checks, premise checks before deductions, and a small router that flags questions worth a second pass.

## Memory

The memory store scores entries by kind, fades routine episodes over time, distills recurring topics into higher-level notes, and asks before deleting anything.

**Layers and kinds.** Entries sit on four abstraction layers: L0 episode (raw event) -> L1 distillate -> L2 core -> L3 meta-frame. Each entry also has a kind: `episodic`, `semantic`, `procedural`, or `identity`.

**Salience and decay.** Decay follows the entry's kind: episodes fade quickly, semantic and procedural notes very slowly, and identity entries never decay. Only episodes can be nominated for removal. Decay is idempotent (recomputed from base score and age), because an earlier compounding version slowly ate away at durable facts; that bug now has its own regression test.

**Hit feedback.** Entries returned by recall get a small salience bump once hit telemetry crosses a minimum volume and diversity threshold, so a handful of repeated test queries cannot skew the weights.

**Dreaming.** A nightly script (`zolander_dream.py`) runs decay, clusters the day's episodes by topic, and distills them into higher layers while preserving explicit dates and times.

**Reversible forgetting.** Decay only nominates candidates. An audit pass proposes a verdict (`forget`, `keep`, or promote to a durable kind), and nothing changes state without human confirmation.

**Recall.** A router classifies each query (point, aggregate, relation, temporal): temporal queries filter out superseded facts, while aggregate ones pull the topic subtree. Search combines BM25 and dense vectors, with the blend weight chosen by a parameter sweep on a gold set (`mem_eval.py`). The eval suite includes knowledge-gap canaries where the answer is absent from memory by design and confident guessing is penalized.

Paper-backed mechanisms and the tests covering them:

| Mechanism | Source | Test |
|---|---|---|
| Salience bump from recall hits (Weighted Memory Tree) | arXiv 2608.20631 | `test_salience_bump.py`, `test_recall_hit_telemetry.py` |
| Reversible forgetting states | arXiv 2608.18177 | `test_reversible_forgetting_state.py` |
| Current-state filter for superseded facts | arXiv 2608.19652 | `test_recall_current_state.py`, `test_when_gate.py` |
| Knowledge-gap canaries with penalty scoring | arXiv 2608.26385 | `test_mem_eval_canary.py` |
| Dream distillation keeps temporal data | arXiv 2608.11775 | `test_dream_preserve_time.py` |
| Structured session recall | arXiv 2608.08300 | `test_zol_session_structured_recall.py` |
| Graph expansion in recall (opt-in) | arXiv 2608.13334, 2608.26983 | `test_recall_graph_expand.py` |
| Rerank cache | arXiv 2608.22767 | `test_mem_rerank_cache.py` |
| Provenance stored with every memory | arXiv 2608.22061 | `test_put_persists_source.py` |
| Anti-fixation note on recalled context (MemTrapBench) | arXiv 2608.20202 | in `hook_recall.py` |
| Judge-scale audit for multi-model review | arXiv 2608.27309 | `test_judge_scale.py`, `test_moa_judge_scale.py` |

Storage currently runs on a single [HyperspaceDB](https://github.com/YARlabs/hyperspace-db) collection (`zol_mem.py`, `mem_store.py`) with kind and layer in metadata.

### What didn't work: hyperbolic hierarchy

The project started from the hypothesis that hyperbolic embeddings would separate levels of abstraction geometrically: broad concepts near the origin, raw episodes near the boundary. I benchmarked that assumption before building the retrieval stack around it ([`abstraction-engine-empirical-test.md`](skills/zolander/references/abstraction-engine-empirical-test.md)):

- Across 516 memories on 4 layers, mean radius moved in the expected direction, but the layer distributions overlapped almost completely.
- Entailment cones (Ganea 2018) scored worse than plain Lorentz distance (AUROC 0.69 vs 0.74).
- On a controlled 5x5 abstraction ladder, the embedder compressed all radii into a ~0.4 band regardless of input specificity, pointing to the embedding model itself as the bottleneck.

Hyperbolic hierarchy gating was dropped on those numbers. Topic clustering kept working, retrieval stayed on hybrid BM25/dense search, and active memory migration targets [Hindsight](https://github.com/vectorize-io/hindsight).

## Voice: Slovak speech-to-text

Stock Whisper struggles with casual spoken Slovak, so `toolkit/stt_whisper.py` wraps a Slovak fine-tune of Whisper large-v3-turbo (`kinit/whisper-large-v3-turbo-sk`) as a Hermes STT command provider and picks an available runtime automatically (Apple MLX, `faster-whisper` on CPU/CUDA, or `transformers`).

I tuned the decode parameters by ablation on real voice notes after noticing the turbo checkpoint stopped transcribing around 40 seconds into longer recordings. Adding a temperature fallback and disabling `condition_on_previous_text` fixed the cutoff, and a short colloquial Slovak prompt primes punctuation and diacritics. Those checks were run manually on audio samples and aren't part of `run_tests.py`.

## Identity

`gen_identity.py` generates an Ed25519 keypair and `integrity.py` checks a SHA-256 manifest of the identity files, so `skills/zolander/SKILL.md` is verified on startup regardless of which model runs the session.

## Install

```bash
bash bootstrap.sh          # venv, deps, identity key, memory collection, systemd timers
hermes model               # pick any LLM provider
```

Wire the hooks in `~/.hermes/config.yaml` (adjust paths to your clone):

```yaml
hooks:
  pre_llm_call:
    - command: python3 /path/to/toolkit/hook_recall.py
    - command: python3 /path/to/toolkit/hook_skill_matcher.py
  pre_tool_call:
    - command: python3 /path/to/toolkit/hook_cmd_guard.py
  pre_verify:
    - command: python3 /path/to/toolkit/hook_verify.py
```

Then allowlist them once with `hermes hooks doctor`.

## LLM access

Toolkit scripts call vendor APIs directly through `toolkit/llm_client.py` (Python stdlib only), reading keys from environment variables first and `~/.hermes/.env` second:

- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` (model IDs containing `/`)
- `ANTHROPIC_BASE_URL`, `GEMINI_BASE_URL`, `OPENAI_BASE_URL` for custom endpoints; `OPENAI_BASE_URL` also works with OpenRouter, Ollama, and LM Studio (any dummy key works for local servers)
- Built-in aliases `opus` and `sonnet` default to `claude-opus-5-5` and `claude-sonnet-5-5`; `gpt`, `gpt-mini`, `gpt55`, `gemini`, `flash`, and `ox` read `LLM_MODEL_<ALIAS>` (for example `LLM_MODEL_GPT_MINI`)
- `LLM_MIN_INTERVAL` sets the minimum delay between calls in seconds (default `0.4`)

## Layout

```
toolkit/   hooks, memory, gates, dream/loop daemons, speech-to-text, tests
skills/    SKILL.md (identity) + references/ (procedures loaded on demand)
deploy/    systemd timers, HyperspaceDB native build
```

## License

MIT
