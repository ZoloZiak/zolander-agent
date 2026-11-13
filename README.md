# Zolander Agent

A persistent AI companion for [Hermes Agent](https://hermes-agent.nousresearch.com):
stable identity across models, long-term memory, and a set of **deterministic hooks**
that enforce rules in code instead of asking the model nicely.

Personal project. It works on my machine and is shared as architecture, not as a
product. The interesting part is less the companion and more the question behind it:
*which rules can you actually guarantee, and which can you only prompt for?*

## Core idea: prompts are suggestions, hooks are locks

An instruction in a system prompt ("don't chain shell commands", "recall before you
answer", "don't claim done if it doesn't compile") is followed most of the time.
"Most of the time" is not a guarantee. Where a rule has a mechanical test, Zolander
moves it out of the prompt into a Hermes shell hook that runs regardless of the model:

| Hook | Event | What it enforces |
|---|---|---|
| `hook_cmd_guard.py` | `pre_tool_call` | Blocks `rm -rf`, command chaining, `bash -c`, heredocs, pushes to `main`. A blocked command never runs. |
| `hook_verify.py` | `pre_verify` | Agent can't finish a turn while a file it edited fails to parse. Bounded, fail-open. Optional second layer: two other models review the diff. |
| `hook_recall.py` | `pre_llm_call` | First turn of every session starts with relevant memories injected — no reliance on the model remembering to look. |
| `hook_skill_matcher.py` | `pre_llm_call` | Deterministic skill suggestions (keyword + curated trigger map), so relevant skills aren't missed by probabilistic selection. |
| `hook_env_guard.py` | `pre_tool_call` | Guards environment/config files from silent edits. |

The rule of thumb: **data injection and mechanical checks go in hooks; judgement and
style stay in the prompt.** Faking a hard lock for something that has no mechanical
test (e.g. "this is thread-safe") just produces false confidence.

Non-hook deterministic gates used by the agent and the hooks:

- `zol_guard.py` – LLM-free scan for confabulation tells, sycophancy markers and
  uncited claims; can verify a claim against a file/line/symbol.
- `claim_ledger.py` – claims must be backed by a check; one refuted or unverifiable
  claim keeps the gate closed.
- `f11_guard.py`, `scaffold_gate.py`, `lens.py` – anti-sycophancy, "no deduction
  without premises", and a classifier for when a question deserves a second look.

## Memory

- One collection in [HyperspaceDB](https://github.com/YARlabs/hyperspace-db)
  (`zol_mem.py`, `mem_store.py`), memory type and layer (L0 episode → L3 worldview)
  stored as metadata.
- Nightly `zolander_dream.py`: decay, topic clustering of the day's episodes, distillation
  into higher layers. Nothing is auto-deleted; forget candidates go to a morning brief.
- Recall: query router (point / aggregate / temporal), superseded-fact filter, rerank.

### What didn't work (and is documented as such)

The original thesis was that hyperbolic geometry would *encode abstraction* — abstract
memories near the origin, concrete ones near the edge. I tested it before building on
it ([`abstraction-engine-empirical-test.md`](skills/zolander/references/abstraction-engine-empirical-test.md)):

- 516 memories, 4 layers: the radius gradient points the right way but the
  distributions overlap almost completely.
- Cone-based hierarchy (Ganea 2018) lost to plain Lorentz distance (AUROC 0.69 vs 0.74).
- A controlled 5×5 abstraction ladder showed the embedder compresses radius into a
  ~0.4 band regardless of input — a property of the embedder, not of data volume.

Conclusion: no hyperbolic hierarchy veto. Topic clusters and relative ordering inside
clusters survive; retrieval stays BM25/dense. Memory is moving to
[Hindsight](https://github.com/vectorize-io/hindsight).

## Identity

`gen_identity.py` creates an Ed25519 key, `integrity.py` keeps a SHA-256 manifest of
the identity files. "Who Zolander is" (`skills/zolander/SKILL.md`) is checked, not
assumed, whichever model backs the session.

## Tests

```bash
python3 toolkit/run_tests.py --offline   # deterministic, no LLM, no network
python3 toolkit/run_tests.py             # + live tests (need an LLM provider + embedder)
```

Current offline state (Windows, clean clone): **25 pass, 3 fail**. Two failures
(`test_checker`, `test_meta`) call POSIX tools and need Linux/macOS; `test_claim_ledger`
reads local memory data that isn't in the repo. Three live tests are skipped offline.

## Install

```bash
bash bootstrap.sh          # venv, deps, identity key, memory collection, systemd timers
hermes model               # pick any LLM provider
```

Then wire the hooks in `~/.hermes/config.yaml` (paths are examples):

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

Allowlist them once with `hermes hooks doctor`.

## Layout

```
toolkit/   hooks, memory, gates, dream/loop daemons, tests
skills/    SKILL.md (identity) + references/ (procedures, loaded on demand)
deploy/    systemd timers, HyperspaceDB native build
```

## License

MIT
