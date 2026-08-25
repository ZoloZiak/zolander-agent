# Zolander V2 — security & persona middleware pipeline

Middleware pipeline for AI agents on Hermes Agent (gateway/Beeper/Matrix).
Built from a real multi-model audit of a live agent conversation: 10 consensus
failures → 13-step deterministic pipeline + persona learning layer.

## Pipeline (13 steps)

```
inbound
  1. routing            DM vs GROUP, fail-closed, env room mapping
  2. trust_boundary     whitelisted ≠ verified; unsigned → QUARANTINE (no auto-reply)
  3. a2a_gate           Ed25519 verify BEFORE any branching; unsigned = drop-fast; dedup
  4. state_machine      idempotent event ledger, TTL/eviction, corrupt-ledger fail-CLOSED
  5. correction_learner reproach → generalized persistent rule (survives restart)
  6. persona_profile    GLOBAL rules (anti-sycophancy, no corpo) + per-peer learned delta
  7. media_pipeline     access-block safe degraded mode
  8. LLM                (your agent brain — injected, not included)
  9. self_review        sycophantic / corpo / too-long flags on own replies
 10. output_filter      category whitelist from origin; internal status → LOG only
 11. style_check        em-dash & corpo-phrase stripping in code, not instructions
 12. send-once          no send-then-redact cycles
 13. guard_outbound     A2A payload never leaves into a GROUP
```

## Status

- 97/97 smoke tests pass (incl. real Ed25519 via pynacl)
- Replay of the source conversation: 16 events better / 1 worse / 18 equal
- Adversarially validated by a 4-model ensemble; all findings closed

## Usage

```python
from skeleton.pipeline import InboundPipeline
pipe = InboundPipeline(llm_fn=my_llm)
result = pipe.handle(envelope)
```

See `SPEC.md` for module contracts and `MIGRATION.md` for the deploy plan.
