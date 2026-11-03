#!/usr/bin/env python3
"""Stop hook: while a plan-loop plan is running with open tasks, continue instead of stopping.

Gives up after MAX_STALLS consecutive continuations in which no new task was ticked,
so a stuck loop still ends. State lives in the OS temp dir, keyed by session id.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from plan_state import emit, find_active_plan, read_event

MAX_STALLS = int(os.environ.get("PLAN_LOOP_MAX_STALLS", "5"))
STATE_DIR = Path(tempfile.gettempdir()) / "plan-loop-stop"


def load_state(key: str) -> dict:
    try:
        return json.loads((STATE_DIR / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(key: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{key}.json").write_text(json.dumps(state), encoding="utf-8")


def main() -> None:
    event = read_event()
    plan = find_active_plan(event.get("cwd"))
    if plan is None or plan.status != "running" or not plan.open_tasks:
        emit({})
        return
    key = "".join(c for c in str(event.get("session_id") or "default") if c.isalnum() or c in "-_")
    state = load_state(key)
    same_plan = state.get("plan") == str(plan.path)
    progressed = not same_plan or plan.done_count > state.get("done", -1)
    stalls = 0 if progressed else state.get("stalls", 0) + 1
    if stalls >= MAX_STALLS:
        # Allow the stop and start counting afresh on the next user turn.
        save_state(key, {"plan": str(plan.path), "done": plan.done_count, "stalls": 0})
        emit({})
        return
    save_state(key, {"plan": str(plan.path), "done": plan.done_count, "stalls": stalls})
    emit(
        {
            "decision": "block",
            "reason": (
                f"plan-loop: {plan.path.relative_to(plan.root)} is running with "
                f"{len(plan.open_tasks)} open task(s). Next: {plan.open_tasks[0]}. "
                "Continue the run loop. If this task cannot proceed, mark it '- [!]' with the reason "
                "and move on; if only blocked tasks remain, report them."
            ),
        }
    )


if __name__ == "__main__":
    main()
