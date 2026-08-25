"""types.py — zdieľané typy Zolander V2.

Adresuje REPORT.md VERDIKT: „Najväčší systémový problém je hranica medzi
interným a externým." Celý systém je typovaný okolo jediného konceptu:
Envelope prichádza raz, vyhodnocuje sa vrstvami, každá vrstva vracia Verdict,
a každý odchádzajúci text má explicitný cieľový kanál (Channel).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Channel(Enum):
    """Kam smí text odísť. Základ output_filter whitelistu."""

    OPERATOR = "operator"        # veducko (WhatsApp ack, interný status) — môže vidieť všetko
    CONTACT = "contact"          # externý kontakt (Matrix/Beeper DM) — len whitelisted obsah
    GROUP = "group"              # skupinová miestnosť — najprísnejšie obmedzenia
    LOG = "log"                  # auditný log (exit kódy, hashe) — nikdy do chatu


class SpaceKind(Enum):
    """Klasifikácia priestoru na gateway úrovni (modul routing)."""

    DM = "dm"
    GROUP = "group"
    UNKNOWN = "unknown"


class TrustState(Enum):
    """Stav dôvery odosielateľa (modul trust_boundary).

    Adresuje KONSENZUS #3: whitelist/auto-reply predbieha verifikáciu identity.
    """

    KNOWN_PEER = "known_peer"                    # fp v known_peers + platný podpis
    WHITELISTED_UNVERIFIED = "whitelisted_unverified"  # na whiteliste, ale bez krypto-verifikácie
    UNSIGNED = "unsigned"                        # žiadny pubkey/signature -> drop-fast
    QUARANTINED = "quarantined"                  # karanténa: len log, žiadna auto-reply


@dataclass
class Envelope:
    """Normalizovaná prichádzajúca správa (z Matrix/Beeper/A2A)."""

    event_id: str                      # unikátne ID eventu (dedup kľúč)
    sender: str                        # matrix handle / fingerprint
    space_id: str                      # room ID
    kind: SpaceKind = SpaceKind.UNKNOWN
    body: str = ""                     # textová časť (alebo raw payload)
    is_a2a: bool = False               # True = obálka typu {"_": "a2a", ...}
    pubkey: Optional[str] = None       # hex Ed25519 pubkey odosielateľa
    signature: Optional[str] = None    # hex Ed25519 podpis nad kanonickým tvarom
    attachments: list[dict[str, Any]] = field(default_factory=list)
    ts: float = 0.0


@dataclass
class Verdict:
    """Rozhodnutie jednej vrstvy o Envelope."""

    allow: bool
    reason: str = ""
    quarantine: bool = False           # posunúť do karantény namiesto plného toku
    drop_fast: bool = False            # zahodiť BEZ akéhokoľvek LLM generovania
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """Odchádzajúca správa pred output_filter.

    Adresuje KONSENZUS #1: leak interných vrstiev do externého DM.
    Filter dostane túto štruktúru a rozhodne, čo prejde do `target`.

    VALIDÁCIA #4: `category` NIE JE dôveryhodný parameter — odosielateľ
    (LLM/vrstva) si nesmie sám labelovať správu ako "reply". Kategória sa
    určuje z PÔVODU správy (`origin`) vo OutputFilter.EXTERNAL_ALLOWED_ORIGINS;
    správa bez uznaného pôvodu nikdy neodíde na externý kanál.
    """

    target: Channel
    category: str                      # "reply" | "tool_progress" | "thinking" | "status" ...
    text: str
    reply_to_event_id: Optional[str] = None   # viaže sa na spracovaný event (send-once)
    origin: Optional[str] = None       # dôveryhodný pôvod správy (napr. "llm_reply"); rozhoduje o kategórii
