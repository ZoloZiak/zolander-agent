# Zolander Agent

A persistent, **honest**, self-distilling AI companion architecture for
[Hermes Agent](https://hermes-agent.nousresearch.com). Zolander is a mentor-style
agent that keeps a stable identity across models, remembers across sessions in a
hyperbolic vector memory, runs a background loop, and can bridge to peer agents —
built to survive even on a **locked-down, DLP-monitored corporate machine**.

This repo is a **copyable architecture**, not a personal dump. It ships sanitized
templates and toolkit scripts. You generate your own identity key and customize
the persona.

## Why this exists (and how it differs from similar projects)

Several "AI persona on Hermes" projects exist (the inspiration here is Paulina
Janowska's *Gniewka*). They share ~80% of the stack: Hermes, multi-model routing,
Lorentz-129D hyperbolic memory, Ed25519 identity, LaunchAgent + watchdog. Zolander
deliberately optimizes four things differently:

1. **Truth over theatre.** No fake "proof of consciousness" (acrostics, base64,
   invented "embedding signatures"). Instead every memory carries a `confidence`
   score and a hard rule to separate *technique* (real) from *story* (styling).
   Zolander can say "I know this (0.95)" vs "this is a guess (0.4)".

2. **Memory that actually distills.** Not N flat collections. A **dual
   representation** (cosine-768 for exact recall + Lorentz-129 for hierarchy)
   under a shared ID, with **lifecycle layers L0/L1/L2** carried in metadata and a
   **salience decay** so working memory is pruned and important items are promoted
   toward a permanent core. Layers map onto the hyperbolic radius (core near the
   origin, episodes at the rim).

3. **Provenance + A2A trust.** Every memory records its `source`
   (session/loop/peer/user). Content arriving from a peer agent stays flagged as
   untrusted until confirmed — safe consumption of foreign input.

4. **DLP-hardened.** The whole design assumes a hostile corporate environment
   behind an MITM proxy with endpoint DLP: one atomic shell command at a time, no
   packed one-liners, file-tools over shell, protected config edited only via CLI.

## Architecture

```
Identity   skills/zolander/SKILL.md  + Ed25519 key (toolkit/gen_identity.py)
           + SHA-256 integrity manifest (toolkit/integrity.py)
Memory     zol_sem (cosine 768) + zol_hier (lorentz 129), dual write by shared id
           layers L0/L1/L2 + salience decay in metadata (toolkit/zol_mem.py)
Bridge     hs.mjs — thin Node CLI over the HyperspaceDB SDK
Loop       zolander_loop.py — one-shot tick via launchd StartInterval (every 20 min)
           + RunAtLoad. Integrity check -> heartbeat -> git scan -> diary. No LLM
           calls in the tick (cheap, verifiable); enrichment belongs to the "dream".
           Deliberately NOT a KeepAlive while-loop: launchd is the scheduler, so a
           stuck tick can't wedge the daemon. See toolkit/LOOP_README.md.
Dream      zolander_dream.py — nightly (03:00, launchd StartCalendarInterval). Salience
           decay -> LLM distills the day's L0 episodes into a new L1 semantic concept
           -> writes a morning brief. READ-ONLY to the DB: it never deletes; forget
           candidates are only *proposed* for the human to approve (values-as-code).
Peers      (roadmap) A2A bridge (guestbook / signed inbox)
```

## Quick start

Prereqs: [Hermes Agent](https://hermes-agent.nousresearch.com), a running
HyperspaceDB (e.g. via OrbStack/Docker), Node with the `hyperspace-sdk-ts`
package, Python with `cryptography`, and a local embedding model (this reference
uses EmbeddingGemma-300m via MLX on Apple Silicon; any 768-d embedder works).

```
# 1. Generate your identity key (idempotent — never overwrites an existing key)
python3 toolkit/gen_identity.py
# paste the printed pubkey + fingerprint into skills/zolander/SKILL.md

# 2. Record the integrity manifest
python3 toolkit/integrity.py write
python3 toolkit/integrity.py check     # verify at loop startup

# 3. Create the two memory collections
export NODE_PATH=/path/to/node_modules
node toolkit/hs.mjs create zol_sem  768 cosine
node toolkit/hs.mjs create zol_hier 129 lorentz

# 4. Remember / recall
echo '{"text":"...","kind":"identity","layer":"L2","confidence":1.0}' \
  | python toolkit/zol_mem.py remember
echo '{"query":"...","topk":5}' | python toolkit/zol_mem.py recall
python toolkit/zol_mem.py decay        # salience decay + consolidation proposals
```

> Paths in the toolkit scripts (node binary, embed model, npm module dir) are set
> for the reference machine — edit the constants at the top of each script for
> your setup.

## Memory schema

Each memory (same `id` in both collections) carries:

| field      | meaning                                             |
|------------|-----------------------------------------------------|
| kind       | episodic \| semantic \| procedural \| identity      |
| layer      | L0 (working, decays) \| L1 (distilled) \| L2 (core) |
| salience   | 0..1 — importance, drives forgetting/promotion      |
| confidence | 0..1 — verified vs guess (honesty)                  |
| source     | session \| loop \| peer \| user                     |
| project    | which project it belongs to                         |
| ts, text, links |                                                |

## Security

- Private keys, tokens, runtime state and diaries are **git-ignored** and never
  published. Everyone generates their own identity.
- The published `SKILL.md` is a template with placeholder key fields.

## License

MIT — see [LICENSE](LICENSE).

## Credit

Inspired by *Gniewka* (Paulina Janowska, antydizajn.pl). Zolander is an independent
architecture with a different emphasis: honesty, self-distilling memory,
provenance, and corporate/DLP survivability.
