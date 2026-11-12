"""Tool and stop decisions shared by the Codex hooks, the omp extension and the CLI.

``decide_tool`` keeps the planning phase read-only outside plan/. For legacy plans and
for the ``shell`` and ``patch`` kinds its reasons are the original Codex hook's reasons,
character for character.

``decide_stop`` keeps a running plan going while there is work left. It gives up after
``PLAN_LOOP_MAX_STALLS`` (default 5) consecutive continuations without progress, so a
stuck loop still ends. Stall state lives in the OS temp dir, keyed by session id, in the
same files and format the original hook used.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from .planfile import Plan

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
GLOB_CHARS = re.compile(r"[*?\[{]")

DEFAULT_MAX_STALLS = 5
STATE_DIR = Path(tempfile.gettempdir()) / "plan-loop-stop"


def inside_plan_dir(root: Path, cwd: str, raw: str) -> bool:
    target = Path(raw.strip())
    if not target.is_absolute():
        target = Path(cwd) / target
    try:
        target.resolve().relative_to((root / "plan").resolve())
        return True
    except ValueError:
        return False


def _write_target(raw: str) -> str:
    """A file:// URL becomes its path; a glob is judged by the prefix before its first wildcard."""
    text = raw.strip()
    if text.startswith("file://"):
        text = unquote(urlparse(text).path)
    match = GLOB_CHARS.search(text)
    return text[: match.start()] if match else text


def decide_tool(
    plan: Optional[Plan],
    cwd: str,
    tool: Optional[str],
    command: str = "",
    paths: Sequence[str] = (),
    label: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (allow, reason). Only a plan in status planning restricts anything.

    tool: "shell" (Codex Bash), "patch" (Codex apply_patch body in command) or "write"
    (target paths; label names the action when there is no path).
    """
    if plan is None or plan.status != "planning":
        return True, ""
    cwd = cwd or ""
    command = command or ""
    prefix = f"plan-loop: {plan.path.name} is still in planning (read-only outside plan/)."
    if tool == "patch":
        targets = [a or b for a, b in PATCH_PATH.findall(command)]
        outside = [t for t in targets if not inside_plan_dir(plan.root, cwd, t)]
        if outside:
            return False, f"{prefix} Blocked edit to: {', '.join(outside)}. Finish the plan and get approval first."
        return True, ""
    if tool == "shell":
        redirects = [t for t in REDIRECT.findall(command) if not inside_plan_dir(plan.root, cwd, t)]
        if MUTATING_SHELL.search(command) or redirects:
            return False, f"{prefix} This shell command looks mutating. Use read-only commands until the plan is approved."
        return True, ""
    if tool == "write":
        if not paths:
            what = label or "a change with no known target path"
            return False, f"{prefix} Blocked {what}. Finish the plan and get approval first."
        outside = [p for p in paths if not inside_plan_dir(plan.root, cwd, _write_target(p))]
        if outside:
            what = label or ", ".join(outside)
            return False, f"{prefix} Blocked {what}. Finish the plan and get approval first."
        return True, ""
    return True, ""


@dataclass
class StopDecision:
    allow: bool
    reason: str
    next: Optional[str]
    stalls: int


def decide_stop(plan: Optional[Plan], session_id: Optional[str], max_stalls: Optional[int] = None) -> Tuple[bool, str]:
    """Return (allow_stop, reason)."""
    decision = evaluate_stop(plan, session_id, max_stalls)
    return decision.allow, decision.reason


def env_max_stalls() -> int:
    try:
        return int(os.environ.get("PLAN_LOOP_MAX_STALLS", str(DEFAULT_MAX_STALLS)))
    except ValueError:
        return DEFAULT_MAX_STALLS


def session_key(session_id: Optional[str]) -> str:
    return "".join(c for c in str(session_id or "default") if c.isalnum() or c in "-_")


def load_stall_state(key: str) -> dict:
    try:
        return json.loads((STATE_DIR / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_stall_state(key: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{key}.json").write_text(json.dumps(state), encoding="utf-8")


def evaluate_stop(plan: Optional[Plan], session_id: Optional[str], max_stalls: Optional[int] = None) -> StopDecision:
    if plan is None or plan.status != "running":
        return StopDecision(True, "", None, 0)
    if plan.legacy:
        if not plan.open_tasks:
            return StopDecision(True, "", None, 0)
        reason = (
            f"plan-loop: {plan.relpath()} is running with "
            f"{len(plan.open_tasks)} open task(s). Next: {plan.open_tasks[0]}. "
            "Continue the run loop. If this task cannot proceed, mark it '- [!]' with the reason "
            "and move on; if only blocked tasks remain, report them."
        )
        return _with_stalls(plan, session_id, max_stalls, plan.done_count, reason, plan.open_tasks[0])
    outcome = _tier_outcome(plan)
    if outcome is None:
        return StopDecision(True, _tier_release_reason(plan), None, 0)
    reason, next_id = outcome
    return _with_stalls(plan, session_id, max_stalls, _progress(plan), reason, next_id)


def _progress(plan: Plan) -> int:
    done = sum(1 for node in plan.nodes if node.mark == "x")
    ran = sum(1 for scenario in plan.scenarios if plan.scenario_status(scenario.id) != "NOT_RUN")
    return done + ran


def _states(plan: Plan) -> Dict[str, str]:
    return {node.id: node.mark_state for node in plan.nodes}


def _tier_outcome(plan: Plan) -> Optional[Tuple[str, Optional[str]]]:
    """(reason, next node) when the run should continue, None when it may stop."""
    states = _states(plan)
    open_nodes = [node for node in plan.nodes if states[node.id] not in ("done", "blocked")]
    runnable = [node for node in open_nodes if all(states.get(dep) == "done" for dep in node.after or [])]
    rel = plan.relpath()
    if runnable:
        node = runnable[0]
        owner = f" (owner: {node.owner})" if node.owner else ""
        reason = (
            f"plan-loop: {rel} is running with {len(open_nodes)} open node(s). "
            f"Next: {node.id} {node.title}{owner}. "
            "Continue the run loop. If a node cannot proceed, mark it '- [!]' with the reason "
            "and move on; if only blocked nodes remain, report them."
        )
        return reason, node.id
    if open_nodes or any(state == "blocked" for state in states.values()):
        return None
    not_run = [s.id for s in plan.scenarios if plan.scenario_status(s.id) == "NOT_RUN"]
    if not_run:
        reason = (
            f"plan-loop: {rel} is running; every node is done but {len(not_run)} scenario(s) are NOT_RUN: "
            f"{', '.join(not_run)}. Run them and record each result before finishing."
        )
        return reason, None
    return None


def _tier_release_reason(plan: Plan) -> str:
    states = _states(plan)
    blocked = [node.id for node in plan.nodes if states[node.id] == "blocked"]
    open_nodes = [node.id for node in plan.nodes if states[node.id] not in ("done", "blocked")]
    rel = plan.relpath()
    if open_nodes:
        return (
            f"plan-loop: {rel} has no runnable node; {', '.join(open_nodes)} wait on blocked "
            f"node(s) {', '.join(blocked)}. Report the blocked nodes."
        )
    if blocked:
        return f"plan-loop: {rel} has only blocked nodes left: {', '.join(blocked)}. Report them."
    return f"plan-loop: {rel} has no open node and no NOT_RUN scenario."


def _with_stalls(
    plan: Plan,
    session_id: Optional[str],
    max_stalls: Optional[int],
    metric: int,
    reason: str,
    next_item: Optional[str],
) -> StopDecision:
    limit = max_stalls if max_stalls is not None else env_max_stalls()
    key = session_key(session_id)
    state = load_stall_state(key)
    same_plan = state.get("plan") == str(plan.path)
    progressed = not same_plan or metric > state.get("done", -1)
    stalls = 0 if progressed else state.get("stalls", 0) + 1
    if stalls >= limit:
        # Allow the stop and start counting afresh on the next user turn.
        save_stall_state(key, {"plan": str(plan.path), "done": metric, "stalls": 0})
        return StopDecision(
            True,
            f"plan-loop: {stalls} continuation(s) in a row without progress on {plan.relpath()}; allowing the stop.",
            next_item,
            stalls,
        )
    save_stall_state(key, {"plan": str(plan.path), "done": metric, "stalls": stalls})
    return StopDecision(False, reason, next_item, stalls)
