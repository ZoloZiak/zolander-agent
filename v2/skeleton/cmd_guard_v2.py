"""cmd_guard_v2 — whitelist prístupu k shell operáciám.

ADRESUJE (REPORT.md):
- UNIKATNY NALEZ [gemini]: „cmd_guard = blacklist, nie whitelist" — obrana
  len proti `rm -rf`, nie proti neznámym príkazom.
- RIESENIA backlog 11 [cmd_guard: whitelist namiesto blacklist]: „povoliť
  len explicitne dovolené príkazy".
- ROZCHODY `rm -rf` incident: [ox] — „NEVERIFIKOVATEĽNÉ z tohto vstupu";
  cmd_guard má mať v logu DÔKAZ bloku, nie existovať ako spomienka
  ([ox] HRANICE diera 3: „Bez logu bloku nemám dôkaz, že guard existuje
  ako kód").
- RIESENIA backlog 13 [Tool-output do dialógu ako dôkaz]: agent má do logu
  písať exit kódy/hashe, nie adjektíva („preventívne odklikol").

Princíp: default DENY. Povolené je len to, čo je explicitne na whiteliste
s obmedzenými argumentmi. Každý pokus (povolený aj zamietnutý) zanechá
auditný záznam s exit kódom/hashom. Plne deterministický modul.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from typing import Optional

from .types import Verdict

#: Placeholder env (žiadne reálne secrets):
#:   ZOLANDER_CMD_WHITELIST="git status,git diff --stat,python3 tools/report.py"
ENV_CMD_WHITELIST = "ZOLANDER_CMD_WHITELIST"


class CmdGuardV2:
    """Whitelist guard nad shell/tool vykonávaním. Default DENY."""

    #: VALIDÁCIA BONUS #7 (ACE cez interpreter whitelist): tieto tokeny ako
    #: hlavička whitelist vzoru = spustenie ľubovoľného kódu. Wildcard
    #: ("python3 *") aj holý interpreter ("python3") sú ZAKÁZANÉ; povolený
    #: je len presný zápis s explicitným skriptom ("python3 tools/x.py").
    INTERPRETER_TOKENS = frozenset({
        "python", "python3", "sh", "bash", "dash", "zsh", "fish", "ksh",
        "node", "nodejs", "deno", "bun", "perl", "ruby", "php", "lua",
        "osascript", "pwsh", "powershell", "awk", "tclsh", "Rscript",
    })

    #: DESTRUCTIVE vzory sú zakázané VŽDY — nedajú sa ani whitelistingnúť.
    #: Adresuje [gemini]: blacklist obrana len proti rm -rf nestačí.
    DESTRUCTIVE_PATTERNS = (
        re.compile(r"\brm\b[^|;&]*\s-{1,2}[a-zA-Z]*[rf]"),   # rm -r / -f / -rf ...
        re.compile(r"\bmkfs(\.\w+)?\b"),
        re.compile(r"\bdd\b[^|;&]*\bof="),
        re.compile(r"\bshred\b"),
        re.compile(r">\s*/dev/(sd|nvme|disk)"),               # > /dev/sd*
        re.compile(r"\bfind\b[^|;&]*\s-delete\b"),
        re.compile(r":\(\)\s*\{.*\}\s*;"),                    # fork bomba
        re.compile(r"\bdiskutil\s+erase"),
        re.compile(r"\bchmod\s+-R\s+[0-7]{3,4}\s+/\s*$"),
        re.compile(r"\bmv\b[^|;&]+\s+/dev/null\s*$"),
        re.compile(r"\bcurl\b[^|;&]*\|\s*(ba)?sh\b"),         # curl | sh
        re.compile(r"\bwget\b[^|;&]*\|\s*(ba)?sh\b"),
        re.compile(r"\bsudo\s+rm\b"),
    )

    def __init__(self, audit_path: str = "cmd_audit.jsonl", env=None) -> None:
        """
        audit_path: append-only JSONL audit log (backlog 13).
        env: injectovateľný mapping (default os.environ) kvôli determinizmu.
        """
        self._env = env if env is not None else os.environ
        self.audit_path = audit_path
        self._allowed_commands: dict[str, str] = {}  # pattern -> popis/pôvod
        self.rejected_entries: list[tuple[str, str]] = []  # (vzor, dôvod) — VALIDÁCIA #7
        self.reload_whitelist()

    # ------------------------------------------------------------------
    # verejné rozhranie
    # ------------------------------------------------------------------

    def evaluate(self, command: str) -> Verdict:
        """Rozhodni o príkaze (deterministicky):
          1. prázdny/nevalidný -> deny,
          2. DESTRUCTIVE vzor -> deny VŽDY (aj keby bol na whiteliste),
          3. command nesedí so žiadnym whitelist vzorom -> deny (default DENY),
          4. whitelist vzor sedí (prefix tokenov; trailing '*' povoľuje
             zvyšné args okrem destructive flagov) -> allow.
        """
        try:
            cmd = (command or "").strip()
            if not cmd or "\n" in cmd:
                return Verdict(allow=False, reason="empty/invalid command")

            tokens = shlex.split(cmd)
            if not tokens:
                return Verdict(allow=False, reason="unparseable command")

            for pat in self.DESTRUCTIVE_PATTERNS:
                if pat.search(cmd):
                    return Verdict(allow=False,
                                   reason=f"destructive pattern blocked: {pat.pattern}")

            match = self._match_whitelist(tokens)
            if match is None:
                return Verdict(allow=False,
                               reason="not whitelisted (default deny)")
            return Verdict(allow=True, reason=f"allowed by whitelist: {match}")
        except ValueError:  # neuzavretý quote v shlex
            return Verdict(allow=False, reason="unparseable command")
        except Exception as exc:  # noqa: BLE001 — fail-closed
            return Verdict(allow=False, reason=f"guard error: {exc}")

    def add_to_whitelist(self, command: str) -> bool:
        """Operátorom schválené pridanie na whitelist; odmietne destructive
        vzory natvrdo (nedajú sa whitelistingnúť). Normalizuje zápis."""
        try:
            cmd = (command or "").strip()
            if not cmd:
                return False
            tokens = shlex.split(cmd)
            if not tokens:
                return False
            probe = self.evaluate(cmd)
            if not probe.allow and "destructive" in probe.reason:
                return False
            # VALIDÁCIA #7: interpreter vzory sa nedajú whitelistingnúť
            risk = self._interpreter_entry_risk(tokens)
            if risk:
                self.rejected_entries.append((cmd, risk))
                return False
            key = " ".join(tokens[:-1]) + (" *" if tokens[-1] == "*" else "")
            if tokens[-1] != "*":
                key = " ".join(tokens)
            self._allowed_commands[key] = "operator-added"
            return True
        except Exception:  # noqa: BLE001
            return False

    def reload_whitelist(self) -> None:
        """Znovunačítaj whitelist z env ZOLANDER_CMD_WHITELIST (bez reštartu).

        VALIDÁCIA #7: interpreter wildcardy ("python3 *") a holé interpretery
        ("bash") sa NEnačítajú — zaznamenajú sa do rejected_entries (audit),
        nepreskočia sa ticho.
        """
        raw = self._env.get(ENV_CMD_WHITELIST, "") if hasattr(self._env, "get") else ""
        loaded: dict[str, str] = {}
        rejected: list[tuple[str, str]] = []
        for entry in (raw or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                tokens = shlex.split(entry)
            except ValueError:
                continue
            if not tokens:
                continue
            risk = self._interpreter_entry_risk(tokens)
            if risk:
                rejected.append((entry, risk))
                continue
            loaded[" ".join(tokens)] = "env"
        self._allowed_commands = loaded
        self.rejected_entries = rejected

    @property
    def whitelist(self) -> tuple[str, ...]:
        """Aktuálne whitelist vzory (read-only pohľad pre audity/testy)."""
        return tuple(sorted(self._allowed_commands))

    def audit_log(self, command: str, allowed: bool,
                  exit_code: Optional[int],
                  output_hash: Optional[str]) -> bool:
        """Zapíš do append-only logu: timestamp, command, rozhodnutie,
        exit_code, sha256 výstupu. Adresuje backlog 13 a [ox] princíp
        „čo nie je v logu, to sa nestalo".

        Vráti True ak zápis prešiel; fail-safe (nikdy nezabiť pipeline).
        """
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "command": command,
            "decision": "ALLOW" if allowed else "DENY",
            "exit_code": exit_code,
            "output_sha256": output_hash,
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.audit_path))
            os.makedirs(directory, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def hash_output(data: bytes) -> str:
        """Pomôcka pre volajúceho: sha256 hex výstupu príkazu (audit)."""
        return hashlib.sha256(data or b"").hexdigest()

    # ------------------------------------------------------------------
    # interné
    # ------------------------------------------------------------------

    def _match_whitelist(self, tokens: list[str]) -> Optional[str]:
        """Nájdi whitelist vzor sediaci s tokenmi príkazu.

        Vzor bez '*' musí sedieť presne; vzor končiaci '*' musí byť prefixom
        a zvyšné argumenty nesmú obsahovať destructive flagy (-r/-f/-rf,
        --force, sudo).

        VALIDÁCIA #7 (belt-and-braces): interpreter wildcardy sa nikdy
        nematnevhodneú, aj keby sa do _allowed_commands dostali obchodom.
        """
        joined = " ".join(tokens)
        # REVALIDÁCIA #3 (belt-and-braces): ak hlavička príkazu JE interpreter
        # (po basename normalizácii) a nesie -c/-m, wildcard alebo je holý,
        # nikdy sa nematnevhodnee — nezávisle od obsahu _allowed_commands.
        if self._interpreter_entry_risk(tokens) is not None:
            return None
        # presná zhoda
        if joined in self._allowed_commands:
            return joined
        # VALIDÁCIA #7: presný interpreter+skript vzor povoľuje len argumenty
        # ZA TÝM ISTÝM skriptom ("python3 tools/x.py --json" pri whiteliste
        # "python3 tools/x.py") — nikdy iný skript ani -c kód. Hlavičky vzorov
        # sa porovnávajú po basename normalizácii (REVALIDÁCIA #3 bypass č. 2).
        for pattern in sorted(self._allowed_commands):
            if pattern.endswith("*"):
                continue
            pat_tokens = pattern.split()
            if (len(pat_tokens) >= 2
                    and self._interpreter_head_token(pat_tokens[0]) in self.INTERPRETER_TOKENS
                    and tokens[:len(pat_tokens)] == pat_tokens):
                return pattern
        # wildcard zhoda
        for pattern in sorted(self._allowed_commands):
            if not pattern.endswith("*"):
                continue
            head = pattern[:-1].strip()
            head_tokens = head.split() if head else []
            if (head_tokens and self._interpreter_head_token(head_tokens[0])
                    in self.INTERPRETER_TOKENS):
                continue  # VALIDÁCIA #7: interpreter wildcard = ACE, nikdy
            n = len(head_tokens)
            if tokens[:n] == head_tokens:
                rest = tokens[n:]
                if any(t in ("-r", "-rf", "-fr", "-f", "--force") for t in rest):
                    return None
                if any(t.startswith("-") and "r" in t.lstrip("-") and t.lstrip("-") in ("rf", "fr")
                       for t in rest):
                    return None
                return pattern
        return None

    @staticmethod
    def _interpreter_head_token(token: str) -> str:
        """REVALIDÁCIA #3 (bypass č. 2, ox): normalizuj hlavičku príkazu na
        basename — „/usr/bin/python3“, „./python3“ aj „python3“ sú ten istý
        interpreter. Bez normalizácie by „/usr/bin/python3 *“ prešiel ako
        ne-interpreter."""
        return os.path.basename((token or "").strip().lower())

    @classmethod
    def _interpreter_entry_risk(cls, tokens: list[str]) -> Optional[str]:
        """VALIDÁCIA #7 (+ REVALIDÁCIA #3): vráť dôvod zamietnutia, ak je
        vzor interpreter-ACE.

        - wildcard za interpreterom („python3 *“) -> ľubovoľný kód,
        - holý interpreter bez argumentu („bash“, „/bin/bash“) -> interaktívny
          shell,
        - REVALIDÁCIA #3 (bypass č. 1, ox): flagy -c/-m (aj kombinácie typu
          -cm) -> kód sa spúšťa priamo z argumentu („python3 -c 'kod'“ =
          plné ACE), povolený zostáva len presný zápis s explicitným
          skriptom.
        Hlavička sa porovnáva po basename normalizácii (_interpreter_head_token).
        """
        if not tokens:
            return None
        head = cls._interpreter_head_token(tokens[0])
        if head not in cls.INTERPRETER_TOKENS:
            return None
        for arg in tokens[1:]:
            stripped = arg.lstrip("-")
            if stripped and stripped.strip("cm") == "":
                return "interpreter code flag (-c/-m) = arbitrary code execution"
        if tokens[-1] == "*":
            return "interpreter wildcard pattern = arbitrary code execution"
        if len(tokens) < 2:
            return "interpreter without explicit script argument"
        return None
