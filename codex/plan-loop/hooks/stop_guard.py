#!/usr/bin/env python3
"""Stop hook: while a plan-loop plan is running with work left, continue instead of stopping.

The decision is planlib's ``decide_stop``. It gives up after PLAN_LOOP_MAX_STALLS (default 5)
consecutive continuations without progress, so a stuck loop still ends. Stall state lives
in the OS temp dir, keyed by session id.
"""

from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = str(Path(__file__).resolve().parent)
if HOOKS_DIR not in sys.path:  # python3 -I does not put the script directory on sys.path
    sys.path.insert(0, HOOKS_DIR)

from plan_state import decide_stop, emit, find_active_plan, read_event  # noqa: E402


def main() -> None:
    event = read_event()
    plan = find_active_plan(event.get("cwd"))
    allow, reason = decide_stop(plan, event.get("session_id"))
    # An allowed stop may still carry an explanation; Codex only needs the empty object.
    emit({} if allow else {"decision": "block", "reason": reason})


if __name__ == "__main__":
    main()
