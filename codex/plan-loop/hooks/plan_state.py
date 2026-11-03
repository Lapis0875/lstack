"""Shared helpers for the plan-loop Codex hooks: locate and parse the active plan."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

OPEN_TASK = re.compile(r"^\s*- \[ \] (.+)$")
DONE_TASK = re.compile(r"^\s*- \[x\] ", re.IGNORECASE)
STATUS = re.compile(r"^status:\s*(\S+)\s*$")


@dataclass
class ActivePlan:
    root: Path
    path: Path
    status: str
    open_tasks: list[str]
    done_count: int


def read_event() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def find_active_plan(cwd: str | None) -> ActivePlan | None:
    """Walk up from cwd to the first directory holding plan/ACTIVE (stop at a .git root)."""
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
    open_tasks: list[str] = []
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


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
