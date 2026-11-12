"""Comparison baseline: the Codex hook logic as it was at commit 7aa60fc.

Copied from codex/plan-loop/hooks/plan_state.py, plan_guard.py and stop_guard.py at that
commit, with the stdin/stdout plumbing replaced by function arguments and return values.
The planlib port must keep this behavior for legacy plans. Do not edit the logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

OPEN_TASK = re.compile(r"^\s*- \[ \] (.+)$")
DONE_TASK = re.compile(r"^\s*- \[x\] ", re.IGNORECASE)
STATUS = re.compile(r"^status:\s*(\S+)\s*$")


@dataclass
class ActivePlan:
    root: Path
    path: Path
    status: str
    open_tasks: List[str]
    done_count: int


def find_active_plan(cwd: Optional[str]) -> Optional[ActivePlan]:
    if not cwd:
        return None
    for directory in [Path(cwd), *Path(cwd).parents]:
        marker = directory / "plan" / "ACTIVE"
        if marker.is_file():
            slug = marker.read_text(encoding="utf-8").strip()
            plan = directory / "plan" / f"{slug}.md"
            return parse_plan(directory, plan) if slug and plan.is_file() else None
        if (directory / ".git").exists():
            return None
    return None


def parse_plan(root: Path, path: Path) -> ActivePlan:
    lines = path.read_text(encoding="utf-8").splitlines()
    status = "unknown"
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            match = STATUS.match(line)
            if match:
                status = match.group(1)
    open_tasks: List[str] = []
    done = 0
    in_tasks = False
    for line in lines:
        if line.startswith("## "):
            in_tasks = line.strip() == "## Tasks"
            continue
        if not in_tasks:
            continue
        match = OPEN_TASK.match(line)
        if match:
            open_tasks.append(match.group(1).strip())
        elif DONE_TASK.match(line):
            done += 1
    return ActivePlan(root=root, path=path, status=status, open_tasks=open_tasks, done_count=done)


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


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def inside_plan_dir(root: Path, cwd: str, raw: str) -> bool:
    target = Path(raw.strip())
    if not target.is_absolute():
        target = Path(cwd) / target
    try:
        target.resolve().relative_to((root / "plan").resolve())
        return True
    except ValueError:
        return False


def guard(event: dict) -> dict:
    cwd = event.get("cwd") or ""
    plan = find_active_plan(cwd)
    if plan is None or plan.status != "planning":
        return {}
    command = str((event.get("tool_input") or {}).get("command") or "")
    tool = event.get("tool_name")
    prefix = f"plan-loop: {plan.path.name} is still in planning (read-only outside plan/)."
    if tool == "apply_patch":
        targets = [a or b for a, b in PATCH_PATH.findall(command)]
        outside = [t for t in targets if not inside_plan_dir(plan.root, cwd, t)]
        if outside:
            return _deny(f"{prefix} Blocked edit to: {', '.join(outside)}. Finish the plan and get approval first.")
    elif tool == "Bash":
        redirects = [t for t in REDIRECT.findall(command) if not inside_plan_dir(plan.root, cwd, t)]
        if MUTATING_SHELL.search(command) or redirects:
            return _deny(f"{prefix} This shell command looks mutating. Use read-only commands until the plan is approved.")
    return {}


def stop(event: dict, state_dir: Path, max_stalls: int) -> dict:
    def load_state(key: str) -> dict:
        try:
            return json.loads((state_dir / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(key: str, state: dict) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{key}.json").write_text(json.dumps(state), encoding="utf-8")

    plan = find_active_plan(event.get("cwd"))
    if plan is None or plan.status != "running" or not plan.open_tasks:
        return {}
    key = "".join(c for c in str(event.get("session_id") or "default") if c.isalnum() or c in "-_")
    state = load_state(key)
    same_plan = state.get("plan") == str(plan.path)
    progressed = not same_plan or plan.done_count > state.get("done", -1)
    stalls = 0 if progressed else state.get("stalls", 0) + 1
    if stalls >= max_stalls:
        save_state(key, {"plan": str(plan.path), "done": plan.done_count, "stalls": 0})
        return {}
    save_state(key, {"plan": str(plan.path), "done": plan.done_count, "stalls": stalls})
    return {
        "decision": "block",
        "reason": (
            f"plan-loop: {plan.path.relative_to(plan.root)} is running with "
            f"{len(plan.open_tasks)} open task(s). Next: {plan.open_tasks[0]}. "
            "Continue the run loop. If this task cannot proceed, mark it '- [!]' with the reason "
            "and move on; if only blocked tasks remain, report them."
        ),
    }
