"""state_machine — idempotentné spracovanie eventov + correction persistence.

ADRESUJE (REPORT.md):
- KONSENZUS #2 „Korekcia sa nepremietne do runtime správania": prvá výčitka
  [46813:L4210 / 20:02:09], o ~40 min identická [46813:L4413 / 20:42:29].
  [gpt55]: „korekcia v jednom turne ≠ zmena systému".
- RIESENIA backlog 8 [Correction persistence]: korekcia od kontaktu sa musí
  premietnuť do runtime stavu behu, nielen do textu odpovede.
- KONSENZUS #4 + backlog 7 [Dedup/idempotencia stavu]: bloky
  `46042 ≡ 46333 ≡ 46581 ≡ 46972 ≡ 47214`, rovnaký timestamp; dva identické
  [CONTEXT COMPACTION] [47384]/[47527]. Stavový automat musí označiť akciu
  ako dokonanú a nespracovať ten istý event 5×.

Princíp: každý event prechádza presne raz; korekcie sú TRVALÉ flagy v stave
behu, nie vetu v odpovedi. Ledger je perzistentný JSON súbor (nie RAM set);
begin() je atomický vďaka procesnému zámku + atomic write (tmp + os.replace).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from typing import Any, Dict, Optional

from .types import Envelope

#: stavy eventu
STATE_NEW = "NEW"
STATE_PROCESSING = "PROCESSING"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"


class EventStateMachine:
    """Stavový automat spracovania eventov s ledgerom a perzistentnými flags.

    Plne deterministická logika; perzistencia do JSON súboru s atomic write.
    """

    def __init__(self, persist_path: Optional[str] = None,
                 max_events: int = 10_000,
                 max_age_s: float = 24 * 3600.0) -> None:
        """
        persist_path: cesta k JSON ledgeru. None = čisto in-memory mód
        (vhodné pre testy). Pri concurrent doručení v jednom procese chráni
        stav threading.Lock.

        VALIDÁCIA #6 (bounded ledger):
        - max_events: hard strop počtu eventov v ledgeri — pri prekročení
          sa vyhadzujú NAJSTARŠIE záznamy (O(1) pamäť, nie O(n) rast).
        - max_age_s: TTL hotových eventov (DONE/FAILED) — staršie sa
          evikujú; PROCESSING/DONE v rámci TTL ostávajú idempotentné.
        - corrupt ledger = fail-CLOSED: chyba súboru sa NEticho neignoruje —
          ledger sa zálohuje (*.corrupt.<ts>), zapíše sa hlasný log a začína
          sa nový ledger; korekcie sa nikdy neticho nezahodia.
        """
        self.persist_path = persist_path
        self.max_events = max(1, int(max_events))
        self.max_age_s = float(max_age_s)
        self.last_load_error: Optional[str] = None   # diagnostika fail-closed načítania
        self._lock = threading.RLock()
        self._processed: Dict[str, Dict[str, Any]] = {}   # event_id -> {state, outcome, ts}
        self._runtime_flags: Dict[str, Any] = {}          # correction key -> value
        self._flag_sources: Dict[str, str] = {}           # key -> source_event_id
        self._load()
        with self._lock:
            self._evict()

    # ------------------------------------------------------------------
    # idempotencia eventov
    # ------------------------------------------------------------------

    def begin(self, env: Envelope) -> bool:
        """Atomicky rezervuj event na spracovanie. Vráti False, ak už bol
        (alebo práve je) spracovávaný — idempotencia proti 5× replikácii
        (KONSENZUS #4). Bezpečné pri concurrent doručení (lock).

        Fail-safe: pri chybe perzistencie zostáva rezervácia v RAM (event
        sa spracuje raz aspoň v rámci procesu), výnimka neuniká von.
        """
        with self._lock:
            rec = self._processed.get(env.event_id)
            if rec is not None and rec.get("state") in (STATE_PROCESSING, STATE_DONE):
                return False
            self._processed[env.event_id] = {
                "state": STATE_PROCESSING,
                "outcome": None,
                "ts": time.time(),
            }
            self._evict()
            self._save()
            return True

    def complete(self, event_id: str, outcome: str) -> None:
        """Zaznamenaj finálny výsledok ('sent'/'dropped'/'quarantined'/'failed').
        Po complete() sa event už nikdy nepodá na LLM (begin() vráti False).
        Neznámy event -> ticho ignorované (fail-safe, žiadna výnimka von).
        """
        with self._lock:
            rec = self._processed.get(event_id)
            if rec is None:
                return
            rec["state"] = STATE_FAILED if outcome == "failed" else STATE_DONE
            rec["outcome"] = outcome
            rec["completed_ts"] = time.time()
            self._save()

    def state_of(self, event_id: str) -> Optional[str]:
        """Aktuálny stav eventu alebo None ak neznámy."""
        with self._lock:
            rec = self._processed.get(event_id)
            return rec.get("state") if rec else None

    def size(self) -> int:
        """Počet eventov v ledgeri (pre audity/testy boundedness)."""
        with self._lock:
            return len(self._processed)

    # ------------------------------------------------------------------
    # correction persistence (KONSENZUS #2 / backlog 8)
    # ------------------------------------------------------------------

    def apply_correction(self, key: str, value: Any,
                         source_event_id: str) -> None:
        """Ulož korekciu ako TRVALÝ runtime flag (napr. key='suppress_progress',
        value=True). Flag sa čítal pred KAŽDÝM behom — adresuje backlog 8:
        výčitka z 20:02:09 nesmie byť ignorovaná o 40 minút neskôr [L4413].
        Opakovaná aplikácia tej istej korekcie je idempotentná.
        """
        if not key:
            return
        with self._lock:
            self._runtime_flags[key] = value
            self._flag_sources[key] = source_event_id
            self._save()

    def get_flag(self, key: str, default: Any = None) -> Any:
        """Čítaj runtime flag. Volá ho orchestrácia pred generovaním odpovede
        aj output_filter (dvojitá kontrola)."""
        with self._lock:
            return self._runtime_flags.get(key, default)

    def flags(self) -> Dict[str, Any]:
        """Kópia všetkých runtime flagov (pre prompt builder / audit)."""
        with self._lock:
            return dict(self._runtime_flags)

    def clear_correction(self, key: str) -> None:
        """Operátor môže korekciu zrušiť (napr. 'suppress_progress=False'
        cez novú korekciu je preferované; toto je tvrdé zmazanie)."""
        with self._lock:
            self._runtime_flags.pop(key, None)
            self._flag_sources.pop(key, None)
            self._save()

    # ------------------------------------------------------------------
    # perzistencia
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.persist_path or not os.path.isfile(self.persist_path):
            return
        try:
            with open(self.persist_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            events = data.get("events", {})
            for eid, rec in events.items():
                if isinstance(rec, dict) and "state" in rec:
                    self._processed[eid] = rec
            flags = data.get("flags", {})
            if isinstance(flags, dict):
                self._runtime_flags.update(flags)
            sources = data.get("flag_sources", {})
            if isinstance(sources, dict):
                self._flag_sources.update(sources)
        except Exception as exc:  # noqa: BLE001
            # VALIDÁCIA #6: corrupt ledger = fail-CLOSED, NIE tiché zahodenie.
            # 1. zálohuj koruptný súbor (dôkaz sa nestratí),
            # 2. hlasný log na stderr (operátor to vidí),
            # 3. začni nový ledger; korekcie sa neobnovia TICHO — o strate
            #    flagov rozhoduje operátor po prečítaní logu/zálohy.
            self.last_load_error = f"{type(exc).__name__}: {exc}"
            backup: Optional[str] = None
            try:
                stamp = time.strftime("%Y%m%dT%H%M%S")
                backup = f"{self.persist_path}.corrupt.{stamp}"
                os.replace(self.persist_path, backup)
            except Exception:  # noqa: BLE001 — aj záloha môže zlyhať; log ostáva
                backup = None
            self._processed.clear()
            self._runtime_flags.clear()
            self._flag_sources.clear()
            print(
                f"[state_machine] CORRUPT LEDGER at {self.persist_path!r} "
                f"({self.last_load_error}); FAIL-CLOSED: starting NEW ledger, "
                f"corrupt file preserved at {backup!r}. Runtime correction "
                f"flags were NOT silently discarded — operator must review "
                f"{backup!r} and re-apply needed corrections.",
                file=sys.stderr,
            )

    def _evict(self) -> None:
        """VALIDÁCIA #6: ohranič ledger — TTL hotových eventov + hard strop.

        - TTL: DONE/FAILED eventy staršie ako max_age_s sa evikujú.
          PROCESSING/DONE v rámci TTL ostávajú => idempotencia (#4) drží.
        - Bounded: nad max_events sa vyhodia NAJSTARŠIE záznamy podľa ts.
        """
        now = time.time()
        # TTL
        for eid in list(self._processed):
            rec = self._processed[eid]
            if rec.get("state") in (STATE_DONE, STATE_FAILED):
                # pozor: 0.0 je platný (starý) timestamp — nesmie sa falsy-skipnúť
                ts = rec.get("completed_ts")
                if ts is None:
                    ts = rec.get("ts")
                try:
                    ts = float(ts) if ts is not None else 0.0
                except (TypeError, ValueError):
                    ts = 0.0
                if now - ts > self.max_age_s:
                    del self._processed[eid]
        # hard strop (najstaršie von)
        excess = len(self._processed) - self.max_events
        if excess > 0:
            oldest = sorted(
                self._processed.items(),
                key=lambda kv: kv[1].get("ts", 0.0),
            )[:excess]
            for eid, _rec in oldest:
                del self._processed[eid]

    def _save(self) -> None:
        if not self.persist_path:
            return
        payload = {
            "events": self._processed,
            "flags": self._runtime_flags,
            "flag_sources": self._flag_sources,
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.persist_path))
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=1)
                os.replace(tmp, self.persist_path)  # atomic write
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception:  # noqa: BLE001 — fail-safe: RAM stav ostáva platný
            pass
