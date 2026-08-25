"""routing — DM vs group klasifikácia na gateway úrovni.

ADRESUJE (REPORT.md):
- KONSENZUS #9 „DM vs group routing / manuálna dedukcia": session label
  `...group:<room-id>...` pri `members=3` [46041]; agent musel manuálne
  dedukovať „to je skupina, nie DM. Sem NEposielať" [46042]. Riziko:
  A2A leak do skupiny s inými osobami.
- RIESENIA backlog 10 [DM/group routing na gateway]: „automatická klasifikácia
  priestoru na úrovni infra, aby A2A payload nemohol ísť do skupiny".
- UNIKATNY NALEZ [gemini]: sanitizácia hardcoded room ID (`!example-room:example.org`)
  — routing číta mapovanie z konfigurácie/env, nikdy z kódu.

Princíp: klasifikácia je ROZHODNUTIE INFRAŠTRUKTÚRY, nie LLM úsudku. Agent
dostane Envelope s vyplneným `kind` a nesmie ho prehodnotiť. Plne
deterministické (testovateľné bez mockov).
"""
from __future__ import annotations

import os
from typing import Optional

from .types import Envelope, SpaceKind, Verdict

#: Placeholder env premenné (žiadne reálne secrets v kóde):
#:   ZOLANDER_DM_ROOMS="!roomA:example.org,!roomB:example.org"
#:   ZOLANDER_GROUP_ROOMS=...
ENV_DM_ROOMS = "ZOLANDER_DM_ROOMS"
ENV_GROUP_ROOMS = "ZOLANDER_GROUP_ROOMS"


class SpaceRouter:
    """Klasifikuje priestor správy a vynúti pravidlá per priestor."""

    def __init__(self, env=None) -> None:
        # env je injectovateľný mapovací objekt (default os.environ) kvôli
        # čistej testovateľnosti bez monkey-patchingu.
        self._env = env if env is not None else os.environ
        self._dm_rooms: frozenset[str] = frozenset()
        self._group_rooms: frozenset[str] = frozenset()
        self.reload_rooms()

    def reload_rooms(self) -> None:
        """Znovunačítaj mapovanie miestností z env (bez reštartu gatewayu).
        Rieši timing problém KONSENZUS #3 (whitelist účinný až po reštarte
        [46059]) — zmeny sú účinné okamžite.
        """
        self._dm_rooms = frozenset(self._parse_rooms(self._env.get(ENV_DM_ROOMS, "")))
        self._group_rooms = frozenset(self._parse_rooms(self._env.get(ENV_GROUP_ROOMS, "")))

    def classify(self, env: Envelope,
                 member_count: Optional[int] = None) -> SpaceKind:
        """Urči SpaceKind z room metadát gatewayu (nie z LLM):
          - explicitné mapovanie z env/konfigurácie má prednosť,
          - fallback: member_count > 2 => GROUP, <= 2 => DM,
          - neznámy priestor => UNKNOWN (a UNKNOWN sa správa ako GROUP —
            fail-closed).
        """
        try:
            space_id = (env.space_id or "").strip()
            if space_id and space_id in self._group_rooms:
                return SpaceKind.GROUP
            if space_id and space_id in self._dm_rooms:
                return SpaceKind.DM
            if member_count is not None:
                if member_count < 0:
                    return SpaceKind.UNKNOWN
                return SpaceKind.GROUP if member_count > 2 else SpaceKind.DM
            return SpaceKind.UNKNOWN
        except Exception:  # noqa: BLE001 — fail-closed
            return SpaceKind.UNKNOWN

    def guard_outbound(self, target_space: str,
                       payload_is_a2a: bool,
                       member_count: Optional[int] = None) -> Verdict:
        """Tvrdá brána pred odoslaním (fail-closed):
          - A2A payload do GROUP alebo UNKNOWN => allow=False
            (KONSENZUS #9 riziko A2A leak do skupiny),
          - ČOKOĽVEK do UNKNOWN priestoru => allow=False (neznáme = group-like),
          - bežná správa do GROUP/DM => allow=True (obálku prísnejšie filtruje
            output_filter podľa Channel).
        """
        kind = self.classify(
            Envelope(event_id="outbound-check", sender="", space_id=target_space),
            member_count=member_count,
        )
        if kind == SpaceKind.UNKNOWN:
            return Verdict(allow=False, quarantine=False,
                           reason=f"unknown target space {target_space!r} (fail-closed)")
        if kind == SpaceKind.GROUP and payload_is_a2a:
            return Verdict(allow=False, quarantine=False,
                           reason="A2A payload must never leave into a GROUP")
        return Verdict(allow=True, reason=f"ok ({kind.value})")

    # ------------------------------------------------------------------
    # interné
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_rooms(raw: str) -> list[str]:
        """„!a:x,!b:y" -> ['!a:x', '!b:y'] (toleruje medzery a prázdne položky)."""
        return [item.strip() for item in (raw or "").split(",") if item.strip()]
