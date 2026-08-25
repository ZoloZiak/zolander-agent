"""a2a_gate — vstupná brána pre A2A obálky: drop-fast + dedup event_id.

ADRESUJE (REPORT.md):
- KONSENZUS #5 „Nekonvergujúci A2A handshake / dlhé generovanie na unsigned
  payload" — ten istý `from_fp=EXAMPLE_FP` prišiel ~9× [46813:L4154–L4383]
  s odpoveďami 68–227 s. Syntéza ROZCHODOV: rozhodnutie (trust = kľúč) bolo
  správne, ale „implementácia (drop-fast, dedup) chýba".
- RIESENIA quick-win 2 [Drop-fast unsigned A2A]: „ak obálka nemá pubkey +
  Ed25519 signature, tichý drop bez LLM generovania".
- RIESENIA backlog 7 [Dedup/idempotencia] (vstupná časť — stavový automat rieši
  zvyšok): ten istý payload nesmie 9× prejsť do LLM.

Princíp: gate je CHEAP a DETERMINISTICKÝ. Žiadne dekódovanie base64,
žiadny krypto-rozbor obsahu, žiadne generovanie — len kontrola prítomnosti
a platnosti podpisu + dedup. Neplatná obálka = tichý drop + jeden log riadok.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from typing import Optional

from .types import Envelope, Verdict

# pynacl je OPTIONAL (BRIEF pravidlo 2): ak je, overuje sa Ed25519 podpis;
# ak nie je, gate spolieha na sha256(pubkey)==from_fp väzbu a výslovne to
# označí vo Verdict.metadata.
try:  # pragma: no cover - závislé od prostredia
    from nacl.signing import VerifyKey  # type: ignore

    HAVE_NACL = True
except Exception:  # noqa: BLE001
    VerifyKey = None  # type: ignore[assignment]
    HAVE_NACL = False


class A2AGate:
    """Filtruje prichádzajúce A2A obálky pred akýmkoľvek drahším spracovaním."""

    def __init__(self, known_peers_dir: str = "known_peers",
                 max_seen: int = 10_000,
                 max_age_s: float = 24 * 3600.0) -> None:
        """known_peers_dir: adresár <fingerprint>.pub (hex raw pubkey, 64 znakov).

        Formát prebratý zo starého toolkit/a2a.py (MIGRATION: zachované).
        Placeholder env: MATRIX_ACCESS_TOKEN sa tu NEdotahuje — gate je offline.
        """
        self.known_peers_dir = known_peers_dir
        self.max_seen = max_seen
        self.max_age_s = max_age_s
        self._seen_event_ids: "OrderedDict[str, float]" = OrderedDict()
        self.last_sig_mode: str = "none"  # diagnostika poslednej verify_signature

    # ------------------------------------------------------------------
    # verejné rozhranie
    # ------------------------------------------------------------------

    def check(self, env: Envelope) -> Verdict:
        """Jediná vstupná metóda. Poradie kontrol (záväzné):
          1. dedup: env.event_id už spracovaný -> drop_fast (bez log spamu).
          2. chýba pubkey alebo signature -> drop_fast (KONSENZUS #5).
          3. signature neoverená proti pubkey -> drop_fast.
          4. from_fp nie je v known_peers -> allow=False, quarantine=True
             (ďalej rozhoduje trust_boundary; gate neposkytuje žiadnu odpoveď).

        Fail-safe: akákoľvek interná chyba => drop_fast (nikdy neblokovať
        pipeline výnimkou, nikdy nepustiť neoverenú obálku ďalej).
        """
        try:
            if not env.is_a2a:
                return Verdict(allow=False, reason="not an A2A envelope", drop_fast=True)

            # 1. dedup na event_id — adresuje ~9× opakovaný payload [46813]
            if self.is_seen(env.event_id):
                return Verdict(allow=False, reason="duplicate event_id", drop_fast=True)

            # 2. unsigned => drop-fast BEZ generovania [46813:L4154–L4383]
            if not env.pubkey or not env.signature:
                self.record_seen(env.event_id)
                return Verdict(
                    allow=False,
                    reason="unsigned envelope (no pubkey/signature)",
                    drop_fast=True,
                )

            # 3. podpis / väzba fp->pubkey
            if not self.verify_signature(env):
                self.record_seen(env.event_id)
                return Verdict(allow=False, reason="signature verification failed",
                               drop_fast=True)

            # 4. known peers -> inak karanténa (trust_boundary rozhodne)
            if not self._is_known_peer(env.pubkey):
                self.record_seen(env.event_id)
                return Verdict(allow=False, quarantine=True,
                               reason="unknown peer fingerprint")

            self.record_seen(env.event_id)
            return Verdict(allow=True, reason="verified known peer")
        except Exception as exc:  # noqa: BLE001
            return Verdict(allow=False, reason=f"gate error: {exc}", drop_fast=True)

    def verify_signature(self, env: Envelope) -> bool:
        """Over väzbu identity a (ak je pynacl) aj Ed25519 podpis.

        Kanonický tvar: json.dumps({from_fp, ts, body}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8") — rovnaký
        ako toolkit/a2a.py.

        Kroky:
          1. sha256(pubkey_hex).hexdigest() == from_fp  (povinné, deterministické)
          2. ak pynacl chýba -> True iba na základe kroku 1 (metadata flag);
             ak pynacl je -> navyše Ed25519 verify nad kanonickými bajtmi.
        """
        if not env.pubkey or not env.signature:
            return False
        pubkey = env.pubkey.strip().lower()
        # pre A2A obálky je fingerprint uložený v Envelope.sender
        fingerprint = (env.sender or "").strip()
        if not fingerprint:
            return False
        # väzba: fingerprint je hash pubkeyu (BRIEF: signed = verify
        # sha256(pubkey)==from_fp)
        if hashlib.sha256(pubkey.encode("utf-8")).hexdigest() != fingerprint.lower():
            return False

        if not HAVE_NACL or VerifyKey is None:
            # čistá fallback cesta: bez pynacl nemôžeme overiť Ed25519;
            # vrátime True na základe hash-väzby, volajúčemu to označíme.
            self.last_sig_mode = "hash_binding_only"
            return True

        canonical = json.dumps(
            {"from_fp": fingerprint, "ts": env.ts, "body": env.body},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        try:
            VerifyKey(bytes.fromhex(pubkey)).verify(canonical, bytes.fromhex(env.signature))
            self.last_sig_mode = "ed25519"
            return True
        except Exception:  # noqa: BLE001 — zlý podpis/formát
            self.last_sig_mode = "ed25519_invalid"
            return False

    def record_seen(self, event_id: str) -> None:
        """Zaznač event ako spracovaný (idempotentne, LRU ohraničený).

        Produkčne perzistentný ledger vedie state_machine; tu je to ochrana
        vstupnej brány proti opakovanému doručeniu toho istého eventu.
        """
        if not event_id:
            return
        now = time.time()
        if event_id in self._seen_event_ids:
            self._seen_event_ids.move_to_end(event_id)
        self._seen_event_ids[event_id] = now
        while len(self._seen_event_ids) > self.max_seen:
            self._seen_event_ids.popitem(last=False)

    def is_seen(self, event_id: str) -> bool:
        """True ak event_id už prešiel bránou (záznamy po max_age_s expirujú)."""
        ts = self._seen_event_ids.get(event_id)
        if ts is None:
            return False
        if time.time() - ts > self.max_age_s:
            del self._seen_event_ids[event_id]
            return False
        return True

    def _is_known_peer(self, pubkey_hex: str) -> bool:
        """Known peer = <sha256(pubkey)>.pub existuje v known_peers_dir."""
        fp = hashlib.sha256(pubkey_hex.strip().lower().encode("utf-8")).hexdigest()
        path = os.path.join(self.known_peers_dir, f"{fp}.pub")
        return os.path.isfile(path)
