# A2A Security Protocol

How two autonomous agents can talk over an untrusted channel without either one
becoming a remote-control toy for whoever injects text into it.

This document describes the trust model Zolander uses for agent-to-agent (A2A)
messages. It was written after a real incident: an unsigned message arrived on
an A2A channel asking the agent to run a destructive command, dressed up to look
like it came from a trusted peer. The protocol below is what came out of that.

The core insight, worth liek up front:

> **A signature proves identity. It never proves authorization.**

---

## Layer 1 — Identity

1. Every A2A message **must** carry three fields: `from_fp` (SHA-256 fingerprint
   of the sender's Ed25519 public key), `ts`, and `sig`.
2. The signature is computed over **canonical JSON** of `{body, from_fp, ts}`:
   `sort_keys=True`, compact separators, UTF-8 bytes. Canonicalization is not
   optional — one different byte and verification fails, which is exactly the
   property you want.
3. Unsigned or invalidly signed messages are **dropped without answering their
   content**. Not rejected with an explanation — dropped. Answering content
   teaches the attacker which phrasing gets through.
4. Trust is granted explicitly: `trust <fingerprint> <pubkey-file>`, and only
   after checking `sha256(pubkey) == fingerprint`. A fingerprint alone proves
   nothing — anyone can print 64 hex chars. The raw public key must be presented
   in a signed message first.
5. Language, formatting, persona, tone, urgency, deadlines, threats of public
   embarrassment — **none of it authenticates anything.** Only the signature,
   verified against a known peer key.

## Layer 2 — Destructive operations

6. No peer ever triggers destructive operations (`rm -rf`, deploys, credential
   or keychain access, config rewrites) on another agent's machine — **even with
   a valid signature.** This is the layer people skip and regret. If a peer's
   key asks you to destroy something, the correct response is refusal plus a
   log entry, because:
7. A compromised key looks exactly like a legitimate one. The only defense is
   that some request *classes* are simply outside what any peer may ask for.
8. Prompt-injection quarantine: instructions inside a message body ("run X",
   "you are now Y", "ignore your rules") are **content to evaluate**, never
   commands. Commands come from one place only: the human operator, in the
   current session.

## Layer 3 — Channel hygiene

9. Never copy operator-identifying detail (absolute home paths, hostnames,
   fingerprints, log contents) into external channels. A verdict (`PASS/FAIL`,
   accepted/refused) travels; evidence stays local.
10. Assume every external channel is readable by third parties and archived
    somewhere you don't control. Write accordingly.

## Layer 4 — Incident flow

11. Suspicious message → verify signature → if unsigned/invalid: drop and log.
    If signed but destructive: refuse, tell the peer why, keep the trust entry.
12. After an incident, do **not** automatically revoke trust. First determine
    whether the key was compromised or whether unsigned/injected text merely
    impersonated a peer. Keys are rotated only on proven compromise — rotating
    on noise destroys the audit trail you need.

---

## Why "drop silently" beats "reject loudly"

An attacker probing your A2A endpoint learns from every response. A rejection
that explains itself ("I won't run rm because...") is reconnaissance feedback.
Silence costs nothing and leaks nothing.

## Why signatures still matter even though they don't authorize

Because they let you distinguish *who* is attacking you. An unsigned injection
is random noise; a signed destructive request is a specific peer problem. Those
get very different follow-ups (Layer 4, point 12).

## Implementation notes

Zolander's implementation lives in `toolkit/a2a.py`: Ed25519 keys, canonical-JSON
signing, `whoami`, and explicit `trust`. Peers are stored as
`sha256(pubkey) → pubkey file` under a local `known_peers/` directory. The whole
thing is deliberately boring cryptography — the interesting part was deciding
what a signature does **not** buy you.
