#!/usr/bin/env python3
"""PreToolUse hook: keep plan-loop's planning phase read-only outside plan/.

The decision is planlib's ``decide_tool``. Codex ``Bash`` is its ``shell`` kind and
``apply_patch`` its ``patch`` kind; any other tool is allowed.
"""

from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = str(Path(__file__).resolve().parent)
if HOOKS_DIR not in sys.path:  # python3 -I does not put the script directory on sys.path
    sys.path.insert(0, HOOKS_DIR)

from plan_state import decide_tool, emit, find_active_plan, read_event  # noqa: E402

TOOL_KINDS = {"Bash": "shell", "apply_patch": "patch"}


def deny(reason: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def main() -> None:
    event = read_event()
    cwd = event.get("cwd") or ""
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    plan = find_active_plan(cwd)
    kind = TOOL_KINDS.get(tool) if isinstance(tool, str) else None
    allow, reason = decide_tool(plan, cwd, kind, command=command)
    if allow:
        emit({})
    else:
        deny(reason)


if __name__ == "__main__":
    main()
