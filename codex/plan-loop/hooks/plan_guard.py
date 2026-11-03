#!/usr/bin/env python3
"""PreToolUse hook: keep plan-loop's planning phase read-only outside plan/."""

from __future__ import annotations

import re
from pathlib import Path

from plan_state import emit, find_active_plan, read_event

PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", re.MULTILINE)
MUTATING_SHELL = re.compile(
    r"(^|[;&|]\s*|\s)("
    r"rm|mv|cp|mkdir|rmdir|touch|tee|chmod|chown|ln|truncate|"
    r"sed\s+-i|perl\s+-pi|"
    r"npm\s+(i|install|uninstall|add)|pnpm\s+(i|install|add|remove)|yarn\s+(add|remove)|pip3?\s+install|"
    r"git\s+(commit|push|reset|checkout|switch|merge|rebase|stash|apply|am|cherry-pick|restore|clean)"
    r")\b"
)
REDIRECT = re.compile(r"(?<![0-9&<>])>>?\s*(?!&|/dev/null)(\S+)")


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


def inside_plan_dir(root: Path, cwd: str, raw: str) -> bool:
    target = Path(raw.strip())
    if not target.is_absolute():
        target = Path(cwd) / target
    try:
        target.resolve().relative_to((root / "plan").resolve())
        return True
    except ValueError:
        return False


def main() -> None:
    event = read_event()
    cwd = event.get("cwd") or ""
    plan = find_active_plan(cwd)
    if plan is None or plan.status != "planning":
        emit({})
        return
    command = str((event.get("tool_input") or {}).get("command") or "")
    tool = event.get("tool_name")
    prefix = f"plan-loop: {plan.path.name} is still in planning (read-only outside plan/)."
    if tool == "apply_patch":
        targets = [a or b for a, b in PATCH_PATH.findall(command)]
        outside = [t for t in targets if not inside_plan_dir(plan.root, cwd, t)]
        if outside:
            deny(f"{prefix} Blocked edit to: {', '.join(outside)}. Finish the plan and get approval first.")
            return
    elif tool == "Bash":
        redirects = [t for t in REDIRECT.findall(command) if not inside_plan_dir(plan.root, cwd, t)]
        if MUTATING_SHELL.search(command) or redirects:
            deny(f"{prefix} This shell command looks mutating. Use read-only commands until the plan is approved.")
            return
    emit({})


if __name__ == "__main__":
    main()
