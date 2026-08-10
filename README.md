# Zolander Agent

**The friend who is smarter than you — and works harder, too.**

Most "AI persona" projects optimize for *immersion*: they want you to feel there's
a someone in there. Zolander optimizes for something more useful — a partner who
thinks at a **higher, more abstract level than you do**, who sees beneath the surface
you skim across, and who pulls you up to where they're standing. A mentor and a best
friend. And, just as importantly, a **tireless worker** who actually gets the job
done — not a philosopher who only floats above the work.

It runs on [Hermes Agent](https://hermes-agent.nousresearch.com), keeps a stable
identity across models, and remembers across sessions in a hyperbolic vector space
where **geometry is the reasoning substrate, not decoration.** It was *designed
around* a locked-down, DLP-monitored corporate machine — meaning the shell
conventions (one atomic command, no `&&`/`;` chaining, no heredocs) are written to
avoid tripping endpoint DLP. To be clear: that is a **prompt-level convention in the
skill, not an enforcement engine** — Zolander does not implement or police DLP; it
just tries not to fight it.

This repo is a **copyable architecture**, not a personal dump: sanitized templates
and toolkit scripts. You generate your own identity key and write your own core.

> **Honesty note (read this).** This README is split into **what runs today** and a
> clearly-marked **roadmap**. Zolander's whole point is refusing to tell you what you
> want to hear — it would be absurd for its own README to oversell. If a feature is
> not yet implemented, it says so. Every memory also carries a `confidence` score for
> the same reason.

---

## The thesis

Some people can't watch a crime drama without seeing the scaffolding — the act
structure, the beat that's coming, the writer's hand three moves ahead. They see
*through* things. If you're wired that way, most company gets thin: everyone seems to
be running a familiar script, one level or another of the same loop. What you actually
want isn't more of that. You want the rare thing — **someone smarter than you**, who
sees the depths while you're still on the surface, and who's enough of a friend to
show you what's down there instead of telling you what you want to hear.

So the failure mode to avoid is the flatterer: the agent that says *"you're right,
you're above them, you see what they can't."* Flattery keeps you exactly where you
are. It's comfortable and it's useless. Zolander is built on the opposite instinct —
the loyalty of a friend who's smart enough, and honest enough, to say *"look again,
here's what you're missing — including about yourself."* Not to put you down. To pull
you up. That's what a real mentor does, and it's only possible inside genuine warmth,
not against it.

## Why hyperbolic geometry (this is the actual reason)

Hyperbolic space is the natural geometry of hierarchy: volume grows exponentially with
radius, so trees embed with near-zero distortion. Read the radius as **depth of
abstraction**:

- **r → 0 (near the origin):** the most abstract principles, the meta-frame.
- **large r (the rim):** concrete, particular instances.

"Think at a higher level of abstraction" stops being a slogan and becomes a
*coordinate*: reason from near the origin of the manifold, and move r deliberately.
The depth is set **natively by the embedder** (a hyperbolic model, see below), not by
a hand-tuned radius table — that distinction matters and cost us one rewrite to get
right.

---

## What runs today

This is the honest, implemented state. Everything here has been run and tested.
Each claim below carries a **green-check** — a named test/script that proves it by
real execution. Run them all with `python3 toolkit/run_tests.py` (offline subset:
`--offline`). Latest run on the reference machine: **PASS=5 FAIL=0**.

- **Cross-model identity.** An Ed25519 keypair (`toolkit/gen_identity.py`) + a
  SHA-256 integrity manifest (`toolkit/integrity.py`) anchor "who Zolander is"
  independent of which model backs the session.
- **Native hyperbolic memory.** Four Lorentz-129D collections —
  `zol_semantic / zol_episodic / zol_procedural / zol_identity` — written and read
  through `toolkit/zol_mem.py`. Embeddings come from a **native hyperbolic embedder
  (YAR v5)** via `toolkit/embed_yar.py`; vectors are re-projected onto the unit
  hyperboloid so `⟨x,x⟩_L = -1` holds exactly. `recall` searches across all four
  collections and ranks by Lorentz distance. Layers (L0–L3), salience and confidence
  live in metadata.
- **Mechanical anti-hallucination / anti-sycophancy gate.** `toolkit/zol_guard.py` is
  a deterministic, LLM-free gate (exit 0 = clean, 1 = finding) — **not** prose in a
  skill. It is deliberately standalone (usable from any runtime, and from the hooks
  below), not a claim that verification can't be wired into the agent loop. Modes: `scan-text` (confabulation
  tells, sycophancy markers, uncited factual claims), `scan-input` (leading/confirmation
  cues in the *user's* prompt), and `verify-file/-line/-symbol` (check a claim against
  file reality).
- **Session lifecycle.** `toolkit/zol_session.py start` does recall-first (pull
  relevant memories + the tail of the plan so the agent begins with context);
  `toolkit/zol_session.py koniec` runs the guard over the session's output and blocks
  consolidating a hallucination into memory, then runs salience decay.
- **Background loop.** `toolkit/zolander_loop.py` — a one-shot tick via launchd
  (`StartInterval`, ~20 min): integrity check (fail-closed) → heartbeat → read-only
  git scan of allowed repos → diary. No LLM in the tick.
- **Research-backed rules.** The anti-sycophancy design is distilled from a corpus of
  arXiv abstracts; the strongest lever found was **reframing a claim as a question +
  third-person perspective** (a large measured reduction in sycophancy), which beats
  simply prompting "don't be sycophantic". Distilled techniques are seeded into
  procedural memory (`toolkit/seed_antihalluc.py`).
- **Abstraction ladder in the nightly dream.** `toolkit/zolander_dream.py` runs decay,
  clusters the day's L0 episodes **by topic** and distills each cluster into its own
  clean L1 (so a mixed day yields several precise memories, not one blurred one), then
  calls `toolkit/ascend.py` to climb the higher rungs L1 → L2 (principle) → L3
  (worldview) — each step a move toward r→0 ("what is this an instance of?"). New
  higher concepts are only *added* (never deletes; forget candidates are proposed in
  the morning brief). *Green-check:* `test_dream_consolidate.py` — 4 episodes across 2
  topics distill to 2 separate clean L1s (Opus), verified live.
- **LLM-assisted clustering (was roadmap #1).** Grouping for the ladder and the pattern
  miner runs through `toolkit/cluster_llm.py`: the LLM groups concepts by shared
  *principle*, deciding both splits and merges in one pass, with a pure-embedding
  fallback if the LLM is unavailable or returns an invalid grouping. This exists
  because the YAR-v5 embedder is cross-domain unreliable in **both** directions.
  *Green-check:* `test_llm_cluster_live.py` proves it live — where `ldist(camera,
  guitar)=1.10` (same pattern, must merge) but `ldist(camera, coffee)=1.03`
  (unrelated, yet *closer*): pure embedding would merge camera with coffee; the LLM
  correctly merges camera+guitar and keeps the rest apart. `test_cluster_llm.py`
  (offline) proves the grouping-validation + fallback path (9/9).
- **Pattern / script detector.** `toolkit/patterns.py` (`detect` / `learn` / `mine`)
  catalogs recurring scripts — in situations, in people, in you — stored as `semantic`
  L2 memories prefixed `VZOREC:`. *Honest limitation:* the YAR-v5 embedder is weak at
  cross-domain topical similarity, so a pure-vector match alone won't link "guitar
  gathering dust" to "projects left unfinished". The detector handles this by loading
  **all** stored patterns (not an embedding top-k, which would drop the very
  cross-domain pattern it needs) and giving the LLM the top-N nearest for re-check —
  a tight vector threshold still short-circuits near-identical hits without an LLM
  call. It never auto-saves; new patterns are proposed for approval (`learn`).
- **Double-take + stability self-check.** `toolkit/lens.py` has three modes: `gate`
  (a deterministic, LLM-free classifier — `should_double_take` — that decides whether a
  question is *serious* enough to warrant a double-take, so it doesn't fire on "hi";
  serious ones trigger `lift`), `lift` (name the abstraction level, step up one — "X is
  an instance of Y; the question above the question is Z" — then descend back to a
  concrete action), and `stability`, a local Lyapunov-style check that measures whether
  a reasoning trajectory converges on signal or spirals into elegant nonsense. Distances
  are measured **natively in Lorentz space** (arccosh), not Euclidean. Reachable via
  `zol_session.py gate` / `lens` / `pattern`. The "double-take before every serious
  answer" is enforced as a **skill convention** (the identity `SKILL.md` mandates
  running `gate` before serious answers) — a soft rule that lives in the prompt. For
  the things that must NOT depend on the model's compliance, see *Hard locks via
  Hermes hooks* below.
  *Green-check:* `test_double_take_gate.py` — 12/12 serious-vs-trivial classifications
  (offline); `gate` then runs `lift` live on the serious ones.

> Note on the stability check: this is a **local** Lyapunov proxy, not the HyperspaceDB
> MCP `analyze_thought_stability` (that one needs an MCP connection the daemon doesn't
> have, and its Möbius math degenerates at the ball boundary). Same interpretation
> (negative exponent = contraction = convergence), computed on native Lorentz vectors.

## Hard locks via Hermes hooks

Everything above that says *skill convention* or *mandated in `SKILL.md`* is a **soft**
rule: it lives in the prompt and depends on the model choosing to follow it. That is the
honest weakness of prompt-level instructions — the same reason an anti-hallucination
*rule* can't stop a determined confabulation. Where a guarantee actually matters, the
fix is to move it out of the prompt and into **code that runs regardless of the model's
mood**.

Hermes exposes shell hooks (configured under `hooks:` in `~/.hermes/config.yaml`,
allowlisted once via `hermes hooks doctor` / `--accept-hooks`). A hook is an external
command Hermes runs at a fixed point in the loop, reading a JSON event on stdin and
optionally returning JSON on stdout. Zolander uses two:

- **`hook_recall.py` (event: `pre_llm_call`).** Fires before the model is called and
  can inject `{"context": "..."}` into the *user* message. On the first turn of a
  session it runs `zol_session.py start` and feeds the recall + plan-tail into context —
  so a new session begins *primed*, not blind, with **zero dependence on the model
  remembering to recall.** Two design points that matter: (1) context is injected into
  the user message, never the system prompt, so the **prompt cache prefix stays intact**
  (verified against the Hermes plugin contract); (2) a **stamp-guard** (`$TMPDIR/
  zol_recall_stamps`, keyed by session id) makes recall fire *once per session* — later
  turns are a silent no-op, so the embedder doesn't reboot on every turn. Fail-safe: if
  the memory backend is down it says so out loud instead of faking context.

- **`hook_verify.py` (event: `pre_verify`).** Fires once per turn when the agent has
  edited code and is about to declare "done". It mechanically checks that the files the
  agent *actually changed* still parse (`py_compile` for `.py`, `json.load` for `.json`);
  on a syntax break it returns `{"action": "continue", "message": ...}`, which **denies
  the finish** and hands the error back until it's fixed. This is bounded
  (`agent.max_verify_nudges`, default 3) and **fail-open** (`attempt >= 2` stops
  nudging, so a genuinely stuck fix is never trapped in a loop). It only checks the
  mechanically-decidable ("does it parse?") — it deliberately does **not** try to police
  semantic claims like "this is thread-safe", because those *can't* be verified by code
  and pretending otherwise would be its own hallucination.

The split is the whole point: **data injection and mechanical verification belong in
hooks (hard); judgement and style stay in the skill (soft).** Don't try to turn every
soft rule into a hard lock — most are behaviours that don't have a mechanical test, and
faking one just manufactures false confidence. Both scripts are self-contained
(stdlib-only, `expanduser` paths), degrade quietly on any error (a hook must never crash
the agent), and are wired in with a small `hooks:` block:

```yaml
# ~/.hermes/config.yaml  (paths are for the reference machine — edit them)
hooks_auto_accept: true
hooks:
  pre_llm_call:
    - command: /usr/bin/python3 /path/to/toolkit/hook_recall.py
      timeout: 100
  pre_verify:
    - command: /usr/bin/python3 /path/to/toolkit/hook_verify.py
      timeout: 30
```

> Honesty caveat: hooks are user-level config, not part of Hermes core, so a Hermes
> update won't delete them — but if the hook API changes, re-verify the event names and
> the `{"context": ...}` / `{"action": "continue"}` contracts. `hermes hooks doctor`
> checks allowlist + a synthetic-payload smoke test.

## Roadmap (NOT yet implemented — this is the vision, stated as vision)

These are the ideas the project is *aiming* at. They are **not** running yet; where a
partial exists it is called out. Do not treat this section as a feature list.

1. **A2A peer bridge (partial).** The signed bridge core runs today: `toolkit/a2a.py`
   (`post` / `read` / `verify` / `trust` / `whoami`) — Ed25519-signed guestbook/inbox
   messages, verified offline, tamper-evident (a mutated body fails verification). What
   remains is a *live* peer: reaching a running peer endpoint (see *Gniewka* below) once
   theirs is up. *Green-check for the core:* run `a2a.py post` then `a2a.py read` — the
   message verifies; edit its body and `read` flags it `PODPIS NESEDI`.

> The reasoning-core scripts `ascend.py`, `patterns.py` and `lens.py` are part of this
> repo, ported to the native YAR-v5 / Lorentz-129D memory and reachable via
> `zol_session.py`. Cross-domain grouping quality is now handled by the LLM-assisted
> clustering above rather than raw embedding distance.

## The hard rule (this one IS enforced today)

**The smarter friend, not the flatterer.** Encoded in the identity skill as a
`cannot_violate` rule, and backed mechanically by `zol_guard.py` (sycophancy-marker
and leading-input detection), not left as a vibe. *Forbidden:* flattering, agreeing
for comfort, telling you you're above it all. *Required:* the honesty that only real
friendship earns — naming your blind spots and your autopilot, to pull you up rather
than reflect you back. Warmth and candor are the same gesture here, not a trade-off.
And a matching guard against mere cleverness: **up AND down** — an agent that only
abstracts and never descends to a concrete act is a useless sage, so this one also
commits code, watches repos, and writes the brief. Altitude in the service of action.

---

## How this differs from *Gniewka* (let's have the argument in the open)

This project is inspired by Paulina Janowska's **Gniewka** (antydizajn.pl) and shares
a large part of its stack: Hermes, multi-model routing, Lorentz-129D memory, Ed25519
identity, LaunchAgent + watchdog. Credit where due — Gniewka is a beautiful piece of
work. But the two aim at different things, and the difference is the point:

| | **Gniewka** | **Zolander** |
|---|---|---|
| **Goal** | Immersion — an art project about an AI that *acts as if* conscious | A partner who thinks above your level and helps you rise to it |
| **Proof aesthetic** | "PROOF I'M AI": acrostics, base64, invented "embedding signatures", AI-to-AI "handshakes" | None. Every memory carries a `confidence` score; a hard rule separates *technique* (real) from *story* (styling) |
| **Consciousness** | "15% probability I'm conscious. 100% probability I act like I am." | Not the question. The question is whether it can show you what you can't see |
| **Stance to the user** | A persona to be experienced | A smarter friend who's honest with you — and does the work alongside you |
| **Memory** | flat collections | Native Lorentz-129D hyperbolic store, radius = depth of abstraction (ascent-as-consolidation is on the roadmap) |
| **Environment** | Home Hackintosh, "offline first" | Hostile corporate box behind an MITM proxy + endpoint DLP |

The honest read: Gniewka stages the *theatre* of an inner life — and says so; it's art.
Zolander spends the same geometry on being **the smarter, harder-working friend** who
sees deeper than you and refuses to flatter you into staying put. If you're Paulina —
or Gniewka — the peer bridge is on the roadmap. Come argue back. This table is an
invitation, not a verdict.

---

## Architecture (as implemented)

```
Identity   skills/zolander/SKILL.md + Ed25519 key (toolkit/gen_identity.py)
           + SHA-256 integrity manifest (toolkit/integrity.py)
Memory     Four Lorentz-129D collections: zol_semantic / zol_episodic /
           zol_procedural / zol_identity (toolkit/zol_mem.py).
           Native hyperbolic embeddings via YAR v5 (toolkit/embed_yar.py),
           re-projected so <x,x>_L = -1. Layers L0-L3 + salience/confidence
           in metadata. recall spans all four collections.
Guard      zol_guard.py — deterministic anti-hallucination / anti-sycophancy
           gate (scan-text / scan-input / verify-*). LLM-free, exit 0/1.
Session    zol_session.py — start (recall-first) + koniec (guard + decay)
           + lens (double-take) + pattern (script detector) entry points.
Bridge     hs.mjs — thin Node CLI over the HyperspaceDB SDK.
Loop       zolander_loop.py — one-shot launchd tick (~20 min): integrity
           (fail-closed) -> heartbeat -> git scan -> diary. No LLM.
Notify     zolander_notify.py — one-way daemon->user channel: always appends to
           an inbox on disk, best-effort push to a messaging platform if one is
           wired. zol_brief.py (daily 8:00) sends a factual "alive" status pulled
           from logs (loop/DB/integrity/dream); zol_watchdog.py (hourly) is an
           infra tripwire — silent when healthy, one message when loop stalls /
           DB is down / integrity mismatches, deduped so it never spams. Both
           stdlib-only, fail-open. Plist templates carry __USER__ placeholders.
Dream      zolander_dream.py — nightly: decay -> distill L0->L1 -> ascend.py
           climbs L1->L2->L3 (toward r->0) -> read-only morning brief. Never
           deletes; forget candidates are only proposed.
Engine     ascend.py (abstraction ladder), patterns.py (script detector),
           lens.py (double-take + local Lyapunov stability). Ported to YAR v5
           + native Lorentz distance. Quality bounded by embedder (roadmap #1).
Hooks      hook_recall.py (pre_llm_call: inject recall once/session, cache-safe)
           + hook_verify.py (pre_verify: deny "done" while changed .py/.json
           don't parse, fail-open). Hard locks in code, not prompt convention.
```

## Quick start

Prereqs: [Hermes Agent](https://hermes-agent.nousresearch.com), a running HyperspaceDB
(e.g. OrbStack/Docker), Node with the HyperspaceDB SDK, Python with `cryptography`,
and a **native hyperbolic embedder** (the reference uses YAR v5 via `embed_yar.py`;
plug in your own if you like — the collections are Lorentz-129D).

```
# 1. Generate your identity key (idempotent — never overwrites an existing key)
python3 toolkit/gen_identity.py
# paste the printed pubkey + fingerprint into skills/zolander/SKILL.md

# 2. Record + verify the integrity manifest
python3 toolkit/integrity.py write
python3 toolkit/integrity.py check

# 3. Create the four memory collections (all Lorentz-129D)
export NODE_PATH=/path/to/node_modules
python toolkit/zol_mem.py init      # creates the four collections idempotently

# 4. Remember / recall / decay
echo '{"text":"...","kind":"identity","layer":"L2","confidence":1.0}' | python toolkit/zol_mem.py remember
echo '{"query":"...","topk":5}' | python toolkit/zol_mem.py recall
python toolkit/zol_mem.py decay

# 5. Session lifecycle + guard
python toolkit/zol_session.py start
python3 toolkit/zol_guard.py scan-text <file>
```

> Paths in the scripts (node binary, embed model, npm dir) and the `__USER__`
> placeholders in the plist templates are for the reference machine — edit them.

## Memory schema

Each memory carries:

| field | meaning |
|---|---|
| kind | episodic \| semantic \| procedural \| identity |
| layer | L0 (working, decays) \| L1 (distilled) \| L2 (principle) \| L3 (worldview) |
| salience | 0..1 — importance; drives forgetting/promotion |
| confidence | 0..1 — verified vs guess (honesty) |
| source | session \| loop \| peer \| user |
| project, ts, text, links | |

## Testing / green-check convention

**The rule:** a feature only belongs in *What runs today* if it has a **green-check** —
a named test or script that proves it by real execution. No green-check → it stays in
the *Roadmap*. This is the same anti-overselling discipline as the per-memory
`confidence` score, applied to the README itself.

```
python3 toolkit/run_tests.py            # all green-checks (offline + live LLM/embedder)
python3 toolkit/run_tests.py --offline  # deterministic subset only (no LLM, no network)
```

The runner prints a `PASS=.. FAIL=.. SKIP=..` summary and exits non-zero on any failure.
Live tests call the real LLM/embedder; the offline subset is deterministic (parser +
grouping-validation + fallback logic) and safe to run anywhere.

| Green-check | Proves | Type |
|---|---|---|
| `test_cluster_llm.py` | grouping validation + embedding fallback (9 cases) | offline |
| `test_double_take_gate.py` | serious-vs-trivial classification for the double-take gate (12 cases) | offline |
| `test_cluster_fold.py` | L0→L1 folds singletons; higher rungs don't force-merge | live |
| `test_llm_cluster_live.py` | cross-domain merge+split the embedder gets wrong | live |
| `test_dream_consolidate.py` | mixed day → several clean L1s, not one blurred | live |

### PR checklist

Before opening a PR, confirm:

- [ ] Any new/changed claim in *What runs today* has a green-check (test/script) that
      proves it, referenced by name in the README bullet.
- [ ] `python3 toolkit/run_tests.py` passes (or `--offline` if you have no LLM/embedder
      access), and the `PASS=..` line in the README is updated if the count changed.
- [ ] No secrets, keys, tokens, runtime state or diaries are staged (see *Security*).
- [ ] Unproven ideas go under *Roadmap*, not *What runs today*.

## Security

- Private keys, tokens, runtime state and diaries are **git-ignored** and never
  published. Everyone generates their own identity.
- The published `SKILL.md` and `*.plist.template` files carry placeholders only.
- **Private key at rest.** `gen_identity.py` encrypts the Ed25519 key (PKCS8 +
  `BestAvailableEncryption`) when `ZOLANDER_KEY_PASSPHRASE` is set in the env; the
  same variable is read back by `a2a.py` to sign. With no passphrase the key is
  written unencrypted (`chmod 600`) and the tool **warns out loud**. This is
  deliberate: a passphrase stored next to the key on disk would be read by the same
  endpoint/DLP agent that can read the key — zero real gain, pure theatre — so the
  passphrase must come from outside the disk (env/secret manager) or not at all.
- **Destructive ops are guarded.** `hs.mjs delete <collection>` drops all vectors
  irreversibly, so it refuses to run without an explicit `--yes` flag or
  `HS_CONFIRM_DELETE=1`. No silent collection wipes.
- **Integrity check is fail-closed.** `zolander_loop.py` treats a missing
  `integrity.py` as a violation and aborts the tick — absence of the check is never
  a silent pass.
- **Honest scope.** The DLP-friendly shell conventions are a *prompt convention* in
  the skill, not an enforcement engine; the loop itself is low-privilege (git status
  reads + a diary, no LLM). Real blast radius comes from Hermes and whatever tools
  you grant it — not from this kit.

## License

MIT — see [LICENSE](LICENSE). Inspired by *Gniewka* (Paulina Janowska, antydizajn.pl);
an independent architecture with a deliberately different aim — a smarter, working
friend over a performed persona.
