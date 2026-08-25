"""Zolander V2 — implementované moduly (fáza 2).

Moduly a ich vazby na REPORT.md:
  output_filter    -> KONSENZUS #1 (leak interných vrstiev) + quick-win 1, 5
  a2a_gate         -> KONSENZUS #5 (drop-fast unsigned, dedup) + quick-win 2
  trust_boundary   -> KONSENZUS #3 (karanténa pre whitelisted-unverified)
  persona_hook     -> KONSENZUS #6 (jazyk-mirror register + anti-korpobot)
  routing          -> KONSENZUS #9 (DM vs group na gateway úrovni)
  state_machine    -> KONSENZUS #2, #4 (idempotencia + correction persistence)
  cmd_guard_v2     -> backlog 11 (whitelist namiesto blacklist) + backlog 13
  media_pipeline   -> KONSENZUS #10 (shell-safe STT/video fallback)
  pipeline         -> orchestrácia v záväznom poradí

Detailná špecifikácia: ../SPEC.md
"""
from .types import Channel, Envelope, OutgoingMessage, SpaceKind, TrustState, Verdict
from .output_filter import OutputFilter
from .a2a_gate import A2AGate
from .trust_boundary import TrustBoundary
from .persona_hook import PersonaHook
from .routing import SpaceRouter
from .state_machine import EventStateMachine
from .cmd_guard_v2 import CmdGuardV2
from .media_pipeline import MediaPipeline, MediaResult
from .pipeline import InboundPipeline

__all__ = [
    "Channel", "Envelope", "OutgoingMessage", "SpaceKind", "TrustState", "Verdict",
    "OutputFilter", "A2AGate", "TrustBoundary", "PersonaHook", "SpaceRouter",
    "EventStateMachine", "CmdGuardV2", "MediaPipeline", "MediaResult",
    "InboundPipeline",
]
