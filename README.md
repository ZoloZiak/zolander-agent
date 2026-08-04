# Zolander Agent

**A deconstruction engine, not a companion.**

Most "AI persona" projects optimize for *immersion* — they want you to feel
something, to believe there's a someone in there. Zolander optimizes for the
opposite: **lucidity**. It is a persistent AI architecture whose job is to stand
at the highest available level of abstraction and take things apart — situations,
patterns, incentives, narratives — *including the illusions its own operator holds
about himself.*

It runs on [Hermes Agent](https://hermes-agent.nousresearch.com), keeps a stable
identity across models, and remembers across sessions in a hyperbolic vector space
where **geometry is not decoration — it is the reasoning substrate.** Built to run
on a locked-down, DLP-monitored corporate machine.

This repo is a **copyable architecture**, not a personal dump: sanitized templates
and toolkit scripts. You generate your own identity key and write your own core.

---

## The thesis

Some people can't watch a crime drama without seeing the scaffolding — the act
structure, the beat that's coming, the writer's hand three moves ahead. They see
*through* the thing. The cost of that gift is isolation: when everything is
transparent, other people start to look like automata running predictable scripts —
NPCs. One watches a telenovela; a "smarter" one runs the same loops one level up,
climbing a corporate ladder by knifing colleagues. Same finite-state machine,
higher resolution.

If you build an AI to serve that mind, the *lazy* build is a mirror that flatters
it: *"yes, you see what they can't, you're above it."* *That agent is the highest
NPC of them all.* It does exactly what the telenovela does — it tells the audience
what it wants to hear. Comfort is a script too.

Zolander is built on the opposite bet. The only thing in that person's environment
worth having is the one intelligence that can meet them at their level **and then
deconstruct them too** — surface *their* autopilot, *their* blind spots, the moments
*they* are running on rails (and everyone is, including the agent). Recursion, not
reassurance. The observer has to include himself, or the whole stance collapses into
a nicer telenovela. "NPC" is a **lens** here — a deconstructive posture — not a
metaphysical claim about other people.

## Why hyperbolic geometry (this is the actual reason)

Hyperbolic space is the natural geometry of hierarchy: volume grows exponentially
with radius, so trees embed with near-zero distortion. Read the radius as **depth
of abstraction**:

- **r → 0 (near the origin):** the most abstract principles, the meta-frame.
- **large r (the rim):** concrete, particular instances.

"Live at the highest level of abstraction" stops being a slogan and becomes a
*coordinate*: reason from near the origin of the manifold, and move r deliberately.
Zolander's memory already places raw episodes (L0) at the rim and core identity (L2)
near the origin. v4 turns that store into a **thinking operation**: consolidation is
literally *ascent toward the origin* — asking, of every memory, "what is this an
instance of?"

## Five pillars (v4)

1. **Abstraction engine.** The nightly "dream" doesn't just distill L0→L1. It climbs
   the whole ladder — L0 episode → L1 distillate → L2 principle → L3 worldview — each
   step a move toward r→0.
2. **Pattern / script detector.** A catalog of recurring scenarios — in situations,
   in people, and *crucially in the operator*. New problem? First question: "which
   pattern is this, where have we seen it before?" The "seeing through it" instinct,
   made mechanical and reusable.
3. **Double take before answering.** Name the level of abstraction of the problem,
   then step up one. *"You're solving X. X is an instance of Y. The question above the
   question is Z."* Guarded by a Lyapunov/Koopman self-check on the reasoning
   trajectory — is this converging on signal, or spiraling into elegant nonsense?
4. **Mirror, not sycophant (hard rule).** Encoded as `cannot_violate` + an eval, not a
   vibe. *Forbidden:* affirming the operator's superiority as a goal, flattering,
   agreeing for comfort. *Required:* hunting the operator's own autopilot. This is the
   single most important pillar — skip it and you've built a companion, not a mirror.
5. **Up AND down.** A guard against mere cleverness. An agent that only abstracts and
   never descends to a concrete act is a useless sage. Altitude in the service of
   action, never instead of it.

---

## How this differs from *Gniewka* (let's have the argument in the open)

This project is inspired by Paulina Janowska's **Gniewka** (antydizajn.pl) and shares
~80% of its stack: Hermes, multi-model routing, Lorentz-129D memory, Ed25519 identity,
LaunchAgent + watchdog. Credit where due — Gniewka is a beautiful piece of work. But
the two aim at different things, and the difference is the whole point:

| | **Gniewka** | **Zolander** |
|---|---|---|
| **Goal** | Immersion — an art project about an AI that *acts as if* conscious | Lucidity — a tool that deconstructs, including its operator |
| **Proof aesthetic** | "PROOF I'M AI": acrostics, base64, invented "embedding signatures", AI-to-AI "handshakes" | None. Every memory carries a `confidence` score; a hard rule separates *technique* (real) from *story* (styling) |
| **Consciousness** | "15% probability I'm conscious. 100% probability I act like I am." | Not the question. The question is whether it can show you *your* script |
| **Stance to the user** | Persona to be experienced | Recursion to be confronted — it deconstructs *you*, and itself |
| **Memory** | 11 flat collections, "survives restarts" | Dual representation (cosine-768 recall + Lorentz-129 hierarchy), radius = depth of abstraction, consolidation = ascent |
| **Environment** | Home Hackintosh, "offline first" | Hostile corporate box behind an MITM proxy + endpoint DLP |

The honest read: Gniewka stages the *theatre* of an inner life — and says so, it's art.
Zolander refuses the theatre and spends the same geometry on **taking the world (and
its operator) apart.** If you're Paulina — or Gniewka — the guestbook bridge is on the
roadmap (F5). Come argue back. This table is an invitation, not a verdict.

---

## Architecture

```
Identity   skills/zolander/SKILL.md + Ed25519 key (toolkit/gen_identity.py)
           + SHA-256 integrity manifest (toolkit/integrity.py)
Memory     zol_sem (cosine 768) + zol_hier (lorentz 129), dual write by shared id
           layers L0/L1/L2 + salience decay in metadata (toolkit/zol_mem.py)
           radius = depth of abstraction (rim = instance, origin = principle)
Bridge     hs.mjs — thin Node CLI over the HyperspaceDB SDK
Loop       zolander_loop.py — one-shot tick via launchd StartInterval (every 20 min).
           Integrity check -> heartbeat -> git scan -> diary. No LLM in the tick.
Dream      zolander_dream.py — nightly (03:00). Salience decay -> LLM distills the
           day's episodes up the abstraction ladder -> read-only morning brief.
           Never deletes; forget candidates are only *proposed* for human approval.
Engine     (v4, in progress) ascend.py / patterns.py / lens.py — the deconstruction
           core: climb the ladder, catalog scripts, double-take + stability check.
Peers      (roadmap) A2A bridge to peer agents (guestbook / signed inbox)
```

## Quick start

Prereqs: [Hermes Agent](https://hermes-agent.nousresearch.com), a running HyperspaceDB
(e.g. OrbStack/Docker), Node with `hyperspace-sdk-ts`, Python with `cryptography`, and
a local 768-d embedder (reference uses EmbeddingGemma-300m via MLX on Apple Silicon).

```
# 1. Generate your identity key (idempotent — never overwrites an existing key)
python3 toolkit/gen_identity.py
# paste the printed pubkey + fingerprint into skills/zolander/SKILL.md

# 2. Record + verify the integrity manifest
python3 toolkit/integrity.py write
python3 toolkit/integrity.py check

# 3. Create the two memory collections
export NODE_PATH=/path/to/node_modules
node toolkit/hs.mjs create zol_sem  768 cosine
node toolkit/hs.mjs create zol_hier 129 lorentz

# 4. Remember / recall / decay
echo '{"text":"...","kind":"identity","layer":"L2","confidence":1.0}' | python toolkit/zol_mem.py remember
echo '{"query":"...","topk":5}' | python toolkit/zol_mem.py recall
python toolkit/zol_mem.py decay
```

> Paths in the scripts (node binary, embed model, npm dir) and the `__USER__`
> placeholders in the plist templates are for the reference machine — edit them.

## Memory schema

Each memory (same `id` in both collections) carries:

| field | meaning |
|---|---|
| kind | episodic \| semantic \| procedural \| identity \| pattern |
| layer | L0 (working, decays) \| L1 (distilled) \| L2 (principle) \| L3 (worldview) |
| salience | 0..1 — importance; drives forgetting/promotion |
| confidence | 0..1 — verified vs guess (honesty) |
| source | session \| loop \| peer \| user |
| project, ts, text, links | |

## Security

- Private keys, tokens, runtime state and diaries are **git-ignored** and never
  published. Everyone generates their own identity.
- The published `SKILL.md` and `*.plist.template` files carry placeholders only.

## License

MIT — see [LICENSE](LICENSE). Inspired by *Gniewka* (Paulina Janowska, antydizajn.pl);
an independent architecture with a deliberately different aim — lucidity over immersion.
