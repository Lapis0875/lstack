"""Shared helpers for the plan-loop Codex hooks: a shim over the skill's planlib.

The only plan parser is ``skills/plan-loop/scripts/planlib`` in this checkout (the hook
commands point at absolute checkout paths, so the skill tree is always beside them).
This module puts that directory on ``sys.path`` and re-exports what the hooks need.

If planlib cannot be imported the hooks fail open: one line on stderr, ``{}`` on stdout,
exit 0. A broken skill tree must never stop Codex from running tools or stopping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "plan-loop" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def read_event() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")


try:
    from planlib.guards import decide_stop, decide_tool
    from planlib.planfile import Plan, find_active_plan, parse_plan
except Exception as exc:  # ImportError, or a SyntaxError from an interpreter too old for planlib
    detail = " ".join(f"{type(exc).__name__}: {exc}".split())
    sys.stderr.write(f"plan-loop: hook disabled, cannot import planlib from {SCRIPTS} ({detail})\n")
    emit({})
    sys.exit(0)

ActivePlan = Plan

__all__ = ["ActivePlan", "Plan", "decide_stop", "decide_tool", "emit", "find_active_plan", "parse_plan", "read_event"]
