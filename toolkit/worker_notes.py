#!/usr/bin/env python3
"""worker_notes.py — orchestračný scratchpad (2608.26480 Zero-Shot orchestration)
+ SKILL.state delta-log (2608.26263).

ScratchPad: append-only JSONL, kam si agent medzi subtaskami odkladá poznámky.
Prežíva medzi krokmi, čítateľný späť ako súhrn — kontext sa nemusí niesť celý
v hlave. skill_delta: auditná stopa zmien skillu (čo/prečo), aby drift nebol
neviditeľný.

Čistý stdlib, offline, fail-safe (nikdy nezhodí volajúceho kvôli I/O).
"""
import json
import os
import time


class ScratchPad:
    """Medzikrokový scratchpad — append-only JSONL, reload-safe."""

    def __init__(self, path):
        self.path = path
        self.entries = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if ln:
                            self.entries.append(json.loads(ln))
        except Exception:
            # poškodený sidecar nesmie zhodiť orchestráciu
            pass

    def add(self, task, note, status="pending"):
        rec = {"task": task or "", "note": note or "",
               "status": status or "pending", "ts": time.time()}
        self.entries.append(rec)
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return rec

    def pending(self):
        return [e for e in self.entries if e.get("status") == "pending"
                and e.get("task")]

    def summary(self):
        lines = []
        for e in self.entries:
            if not e.get("task"):
                continue
            mark = {"done": "✓", "pending": "…"}.get(e.get("status"), "•")
            lines.append(f"[{mark}] {e['task']}: {e['note']}")
        return "\n".join(lines)


def log_delta(path, skill, change, why):
    """Zapíš zmenu skillu do delta-logu (auditná stopa driftu)."""
    rec = {"skill": skill, "change": change, "why": why, "ts": time.time()}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def read_deltas(path):
    out = []
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if ln:
                        out.append(json.loads(ln))
    except Exception:
        pass
    return out
