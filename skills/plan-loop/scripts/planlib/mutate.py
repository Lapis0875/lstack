"""Plan changes: line-level markdown edits and the advance/node/scenario/sync operations.

Every operation validates first and returns a ``Change`` (new plan bytes, new state
document, envelope data) or raises ``Refused``; nothing touches the disk until ``apply``
writes the change. ``apply`` checks every destination before it writes and puts back the
files it already replaced when a later step fails, so a refused or failed command leaves
the plan and the state document as they were. Edited lines keep their original line ends;
inserted lines use the file's dominant line end.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import checks, state
from .planfile import NODE_HEAD, TEAM_TIERS, HeadSegment, Node, Plan, head_segments, parse_bytes

LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
ENDING = re.compile(r"(\r\n|\r|\n)\Z")
MARK = re.compile(r"^- \[[ xX!]\]")
BLOCKED_FIELD = re.compile(r"^ {2,}- blocked:")
PLAN_TRANSITIONS = ("approved", "running", "done", "abandoned")


class Refused(Exception):
    """A command that must not change anything. code is the CLI exit code (1, 2, 3 or 4)."""

    def __init__(self, code: int, message: str, findings: Optional[List[checks.Finding]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.findings = list(findings or [])


class WriteFailed(Exception):
    """Writing a change failed part way. The message says whether every file was put back."""

    code = 2

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.findings: List[checks.Finding] = []


@dataclass
class Change:
    data: dict
    text: str
    plan_path: Optional[Path] = None
    plan_bytes: Optional[bytes] = None  # None: the plan file stays as it is
    state_path: Optional[Path] = None
    state_doc: Optional[dict] = None  # None: the state document stays as it is
    remove_active: Optional[Path] = None
    plan: Optional[Plan] = None  # the plan after the change


# --------------------------------------------------------------------------- line editor


class Editor:
    """Edits addressed by 0-based line index of the parsed plan; rendered in one pass."""

    def __init__(self, plan: Plan) -> None:
        text = plan.raw.decode("utf-8")
        self.lines = LINE.findall(text)
        if len(self.lines) != len(plan.lines):
            raise Refused(2, "cannot edit the plan: its line structure is ambiguous")
        self.newline = plan.newline
        self.replaced: Dict[int, str] = {}
        self.deleted: set = set()
        self.inserted: Dict[int, List[str]] = {}

    def body(self, index: int) -> str:
        line = self.replaced.get(index, self.lines[index])
        body = ENDING.sub("", line)
        return body[1:] if index == 0 and body.startswith("\ufeff") else body

    def replace(self, index: int, body: str) -> None:
        original = self.lines[index]
        ending = ENDING.search(original)
        prefix = "\ufeff" if index == 0 and original.startswith("\ufeff") else ""
        self.replaced[index] = prefix + body + (ending.group(1) if ending else "")

    def delete(self, index: int) -> None:
        self.deleted.add(index)

    def insert_after(self, index: int, body: str) -> None:
        self.inserted.setdefault(index, []).append(body)

    @property
    def changed(self) -> bool:
        return bool(self.deleted or self.inserted or any(self.lines[i] != v for i, v in self.replaced.items()))

    def render(self) -> bytes:
        out: List[str] = []
        for index, original in enumerate(self.lines):
            if index not in self.deleted:
                out.append(self.replaced.get(index, original))
            for body in self.inserted.get(index, []):
                if out and not ENDING.search(out[-1]):
                    out[-1] += self.newline
                out.append(body + self.newline)
        return "".join(out).encode("utf-8")


def set_front_matter(editor: Editor, plan: Plan, key: str, value: str) -> None:
    line = plan.front_matter_lines.get(key)
    if line is not None:
        editor.replace(line - 1, f"{key}: {value}")
        return
    anchor = plan.front_matter_lines.get("status")
    if anchor is None:
        raise Refused(2, f"front matter has no status: line to put {key}: after")
    editor.insert_after(anchor - 1, f"{key}: {value}")


def set_mark(editor: Editor, node: Node, mark: str) -> None:
    index = node.line - 1
    editor.replace(index, MARK.sub(f"- [{mark}]", editor.body(index), count=1))


def add_node_field(editor: Editor, node: Node, key: str, value: str) -> None:
    editor.insert_after(node.end - 1, f"  - {key}: {value}")


def _head(editor: Editor, node: Node) -> Optional[Tuple[str, List[HeadSegment]]]:
    """The node head split as the parser splits it: (text up to the title, segments)."""
    body = editor.body(node.line - 1)
    match = NODE_HEAD.match(body)
    if match is None:
        return None
    return body[: match.start(3)], head_segments(match.group(3))


def _set_head(editor: Editor, node: Node, prefix: str, segments: List[HeadSegment]) -> None:
    editor.replace(node.line - 1, prefix + " — ".join(piece for segment in segments for piece in segment.parts))


def set_blocked_field(editor: Editor, node: Node, reason: str) -> None:
    """Record the reason on one indented ``  - blocked:`` line, whose value runs to the line end.

    The reason is free text. In the head it would be split at ` — ` and could turn into other
    fields, so an inline ` — blocked:` piece is dropped and the reason always goes on a field line.
    """
    _drop_inline_blocked(editor, node)
    written = False
    for index in range(node.line, node.end):
        if BLOCKED_FIELD.match(editor.body(index)):
            if written:
                editor.delete(index)
            else:
                editor.replace(index, f"  - blocked: {reason}")
                written = True
    if not written:
        add_node_field(editor, node, "blocked", reason)


def _drop_inline_blocked(editor: Editor, node: Node) -> None:
    head = _head(editor, node)
    if head is not None and any(segment.key == "blocked" for segment in head[1]):
        prefix, segments = head
        _set_head(editor, node, prefix, [segment for segment in segments if segment.key != "blocked"])


def remove_blocked_fields(editor: Editor, node: Node) -> None:
    for index in range(node.line, node.end):
        if BLOCKED_FIELD.match(editor.body(index)):
            editor.delete(index)
    _drop_inline_blocked(editor, node)


# --------------------------------------------------------------------------- session


@dataclass
class Session:
    """The plan, its state document location and the in-memory reconciled state."""

    plan: Plan
    at: str
    by: str = ""
    location: state.Location = field(default_factory=lambda: state.Location(False))
    existed: bool = False
    doc: Optional[dict] = None  # reconciled working copy; None without a state document

    @property
    def stateful(self) -> bool:
        return self.location.declared

    def states(self) -> Dict[str, str]:
        if self.doc is not None:
            return state.node_states(self.doc)
        return {node.id: node.mark_state for node in self.plan.nodes}


def _load_previous(plan: Plan, location: state.Location) -> Optional[dict]:
    if location.problem:
        raise Refused(2, location.problem)
    if location.occupied:
        raise Refused(2, f"{location.relpath} is not a regular file; move it away, then run sync")
    if not location.exists:
        return None
    try:
        return state.load(location.path, plan)
    except state.StateError as exc:
        findings = [checks.Finding("E-STATE-SCHEMA", f"{location.relpath}: {p}") for p in exc.problems]
        raise Refused(1, f"{location.relpath} is invalid; fix it or delete it and run sync", findings) from None


def _checked(session_location: state.Location, doc: dict) -> dict:
    problems = state.validate(doc)
    if problems:
        findings = [checks.Finding("E-STATE-SCHEMA", f"{session_location.relpath}: {p}") for p in problems]
        raise Refused(1, "the plan cannot be recorded in the state document; run check", findings)
    return doc


def open_session(plan: Plan, at: str, by: str = "", need_file: bool = False) -> Session:
    location = state.locate(plan)
    session = Session(plan=plan, at=at, by=by or "", location=location)
    if not location.declared:
        if need_file:
            raise Refused(2, "requires a state document (front matter state:)")
        return session
    previous = _load_previous(plan, location)
    if previous is None and need_file:
        raise Refused(2, f"{location.relpath} does not exist; run sync first")
    session.existed = previous is not None
    session.doc = state.sync(plan, previous, at, by).doc
    return session


def _finish(session: Session, editor: Optional[Editor], data: dict, text: str) -> Change:
    """Re-parse the edited plan, sync the state document and package the change."""
    plan = session.plan
    new_bytes = editor.render() if editor is not None and editor.changed else None
    new_plan = parse_bytes(plan.root, plan.path, new_bytes) if new_bytes is not None else plan
    doc = None
    if session.doc is not None:
        doc = _checked(session.location, state.sync(new_plan, session.doc, session.at, session.by).doc)
    return Change(
        data=data,
        text=text,
        plan_path=plan.path,
        plan_bytes=new_bytes,
        state_path=session.location.path if doc is not None else None,
        state_doc=doc,
        plan=new_plan,
    )


def _unchanged(session: Session, data: dict, text: str) -> Change:
    return Change(data=data, text=text, plan=session.plan)


def _no_newline(*values: Optional[str]) -> None:
    for value in values:
        if value is not None and ("\n" in value or "\r" in value):
            raise Refused(2, "values must be a single line")


# --------------------------------------------------------------------------- sync


def sync(plan: Plan, at: str, by: str = "") -> Change:
    location = state.locate(plan)
    if plan.legacy or not location.declared:
        raise Refused(2, "sync needs a state document (front matter state:)")
    result = state.sync(plan, _load_previous(plan, location), at, by, explicit=True)
    doc = _checked(location, result.doc)
    data = {
        "path": location.relpath,
        "created": result.created,
        "revision": doc["plan"]["revision"],
        "reconciled": result.reconciled,
        "stale": result.stale,
    }
    text = (
        f"sync: {location.relpath} {'created' if result.created else 'updated'} revision={data['revision']} "
        f"reconciled={', '.join(result.reconciled) or '-'} stale={', '.join(result.stale) or '-'}"
    )
    return Change(data=data, text=text, state_path=location.path, state_doc=doc, plan=plan)


# --------------------------------------------------------------------------- advance


def _errors(findings: List[checks.Finding]) -> List[checks.Finding]:
    return [finding for finding in findings if finding.severity == "error"]


def _active_file(plan: Plan) -> Optional[Path]:
    marker = plan.root / "plan" / "ACTIVE"
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == plan.slug:
            return marker
    except (OSError, UnicodeDecodeError):
        return None
    return None


def advance(plan: Plan, target: str, at: str, by: str = "") -> Change:
    current = plan.status
    data = {"from": current, "to": target, "review": None, "activeRemoved": False, "requirementsTicked": []}
    if "status" not in plan.front_matter_lines:
        raise Refused(2, "front matter has no status: line")
    if plan.legacy:
        if target == "done" and plan.open_tasks:
            finding = checks.Finding("E-FINISH-OPEN", f"{len(plan.open_tasks)} open task(s) remain; first: {plan.open_tasks[0]}")
            raise Refused(1, "the done gate failed", [finding])
        session = Session(plan=plan, at=at, by=by)
        if current == target:
            return _unchanged(session, data, f"advance: already {target}")
        editor = Editor(plan)
        set_front_matter(editor, plan, "status", target)
        return _finish(session, editor, data, f"advance: {current} -> {target}")

    try:
        session = open_session(plan, at, by)
    except Refused:
        if target != "abandoned":
            raise
        # Abandoning is always allowed; an unreadable state document is left as it is.
        session = Session(plan=plan, at=at, by=by)
    editor = Editor(plan)
    review: Optional[str] = None
    if target == "approved":
        if current not in ("planning", "approved"):
            raise Refused(1, f"only a planning plan can be approved; this plan is {current}")
        gate = _errors(checks.run_checks(plan, "approve"))
        if gate:
            raise Refused(1, "the approval gate failed", gate)
        review = "waived" if plan.waivers else "passed"
        if current == target and plan.review == review:
            data["review"] = review
            return _unchanged(session, data, f"advance: already approved (review: {review})")
        set_front_matter(editor, plan, "status", target)
        set_front_matter(editor, plan, "review", review)
        data["review"] = review
    elif target == "running":
        if current not in ("approved", "running"):
            raise Refused(1, f"only an approved plan can start running; this plan is {current}")
        if current == target:
            return _unchanged(session, data, "advance: already running")
        set_front_matter(editor, plan, "status", target)
    elif target == "done":
        if current == "done":
            return _unchanged(session, data, "advance: already done")
        if current != "running":
            raise Refused(1, f"only a running plan can be done; this plan is {current}")
        gate = _errors(checks.run_checks(plan, "finish"))
        if session.doc is not None:
            gate.extend(state.stale_done_findings(plan, session.doc))
        if gate:
            raise Refused(1, "the done gate failed", gate)
        set_front_matter(editor, plan, "status", target)
        ticked = []
        for requirement in plan.requirements:
            linked = [s for s in plan.scenarios if requirement.id in s.requirements]
            if not requirement.done and linked and all(plan.scenario_status(s.id) == "PASS" for s in linked):
                editor.replace(requirement.line - 1, MARK.sub("- [x]", editor.body(requirement.line - 1), count=1))
                ticked.append(requirement.id)
        data["requirementsTicked"] = ticked
    elif target == "abandoned":
        if current != target:
            set_front_matter(editor, plan, "status", target)
    else:
        raise Refused(2, f"unknown status {target}")

    remove = _active_file(plan) if target in ("done", "abandoned") else None
    data["activeRemoved"] = remove is not None
    if not editor.changed and remove is None:
        return _unchanged(session, data, f"advance: already {target}")
    if session.doc is not None and current != target:
        state.add_event(session.doc, "plan.status", at, by=by, data={"from": current, "to": target})
    text = f"advance: {current} -> {target}"
    if review:
        text += f" (review: {review})"
    if data["requirementsTicked"]:
        text += f"; requirements checked: {', '.join(data['requirementsTicked'])}"
    if remove is not None:
        text += "; plan/ACTIVE removed"
    change = _finish(session, editor, data, text)
    change.remove_active = remove
    return change


# --------------------------------------------------------------------------- node


@dataclass
class NodeOptions:
    by: Optional[str] = None
    agent: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    evidence: Optional[str] = None
    reason: Optional[str] = None
    cascade: bool = False


def _waiting_on(plan: Plan, node: Node, states: Dict[str, str]) -> List[str]:
    return [dep for dep in node.after or [] if states.get(dep) != "done"]


def _waiting_message(node: Node, waiting: List[str], states: Dict[str, str]) -> str:
    described = ", ".join(f"{dep} ({states.get(dep, 'unknown')})" for dep in waiting)
    return f"{node.id} waits on {described}"


def _clean(value: Optional[str]) -> Optional[str]:
    """Strip a recorded identifier; an empty one is no identifier."""
    if value is None:
        return None
    return value.strip() or None


def _node_view(plan: Plan, states: Dict[str, str], node_id: str) -> dict:
    for view in checks.node_views(plan, states):
        if view["id"] == node_id:
            return view
    raise KeyError(node_id)


def node_command(plan: Plan, action: str, node_id: str, options: NodeOptions, at: str) -> Change:
    if plan.legacy:
        raise Refused(2, "node commands need a plan with a tier: front matter key")
    node = plan.node(node_id)
    if node is None:
        raise Refused(2, f"no node {node_id} in {plan.relpath()}")
    _no_newline(options.evidence, options.reason, options.by, options.agent)
    needs_file = action in ("start", "claim", "fail")
    if action == "block" and not options.reason:
        raise Refused(2, "node block needs --reason")
    if action == "claim" and plan.tier == "workflow" and _clean(options.agent) is None:
        raise Refused(2, "a workflow claim needs --agent naming the agent that did the work")
    session = open_session(plan, at, options.by or "", need_file=needs_file)
    states = session.states()
    current = states[node.id]
    entry = state.node_entry(session.doc, node.id) if session.doc is not None else None
    editor = Editor(plan)
    cascaded: List[str] = []

    def unchanged(message: str) -> Change:
        data = {"action": action, "node": _node_view(plan, states, node.id), "planEdited": False, "cascaded": []}
        return _unchanged(session, data, message)

    by = options.by or ""
    if action == "start":
        if current == "running":
            return unchanged(f"node start {node.id}: already running")
        if current != "pending":
            raise Refused(4, f"{node.id} is {current}; start needs a pending node")
        waiting = _waiting_on(plan, node, states)
        if waiting:
            raise Refused(4, _waiting_message(node, waiting, states))
        blockers = checks.wave_blockers(plan, node, states)
        if blockers:
            raise Refused(4, f"{node.id} is in wave {node.wave}; earlier waves are still open: {', '.join(blockers)}")
        if node.is_gate:
            busy = [n for n, s in states.items() if s in ("running", "claimed")]
            if busy:
                raise Refused(4, f"gate {node.id} cannot start while {', '.join(busy)} are running or claimed")
        entry["state"] = "running"
        entry["startedAt"] = at
        state.add_event(session.doc, "node.started", at, node=node.id, by=by)
    elif action == "claim":
        if current == "claimed":
            return unchanged(f"node claim {node.id}: already claimed")
        if current != "running":
            raise Refused(4, f"{node.id} is {current}; claim needs a running node (node start first)")
        executor = {"agent": _clean(options.agent), "provider": options.provider, "model": options.model, "effort": options.effort}
        entry["state"] = "claimed"
        entry["executor"] = executor
        if options.evidence:
            entry["evidence"].append(options.evidence)
        state.add_event(session.doc, "node.claimed", at, node=node.id, by=by, data={"executor": executor, "evidence": options.evidence})
    elif action == "done":
        if current == "done":
            return unchanged(f"node done {node.id}: already done")
        if current == "blocked":
            raise Refused(4, f"{node.id} is blocked; reset it first")
        if plan.tier in TEAM_TIERS:
            waiting = _waiting_on(plan, node, states)
            if waiting:
                raise Refused(4, _waiting_message(node, waiting, states))
        if node.gate == "test":
            not_run = [s for s in node.scenarios or [] if plan.scenario_status(s) == "NOT_RUN"]
            if not_run:
                raise Refused(4, f"test gate {node.id} still has NOT_RUN scenarios: {', '.join(not_run)}")
        if plan.tier == "workflow" and not node.is_gate:
            if current != "claimed":
                raise Refused(4, f"workflow node {node.id} is {current}; it must be claimed before done")
            claimer = _clean(entry["executor"]["agent"]) if entry is not None else None
            if claimer is None:
                raise Refused(
                    4,
                    f"{node.id} was claimed without an agent; send it back with node fail {node.id}, "
                    "then start it and claim it again with --agent",
                )
            if not by.strip():
                raise Refused(4, f"workflow node {node.id} needs --by naming who confirmed it")
            if by.strip() == claimer:
                raise Refused(4, f"{by} claimed {node.id}; another agent must confirm it")
        set_mark(editor, node, "x")
        if options.evidence:
            add_node_field(editor, node, "evidence", options.evidence)
        if entry is not None:
            entry["state"] = "done"
            entry["finishedAt"] = at
            entry["confirmedBy"] = by or None
            if options.evidence:
                entry["evidence"].append(options.evidence)
            state.add_event(session.doc, "node.done", at, node=node.id, by=by, data={"evidence": options.evidence})
    elif action == "fail":
        if current not in ("running", "claimed"):
            raise Refused(4, f"{node.id} is {current}; fail needs a running or claimed node")
        attempt = entry["attempt"] + 1
        limit = plan.policy.get("max-attempts", 2)
        entry["attempt"] = attempt
        entry["lastError"] = options.reason
        blocked = attempt >= limit
        if blocked:
            reason = options.reason or f"failed {attempt} attempt(s)"
            entry["state"] = "blocked"
            set_mark(editor, node, "!")
            set_blocked_field(editor, node, reason)
        else:
            entry["state"] = "pending"
        state.add_event(
            session.doc, "node.failed", at, node=node.id, by=by, data={"attempt": attempt, "blocked": blocked, "reason": options.reason}
        )
    elif action == "block":
        if current == "blocked":
            return unchanged(f"node block {node.id}: already blocked")
        if current == "done":
            raise Refused(4, f"{node.id} is done; reset it before blocking")
        set_mark(editor, node, "!")
        set_blocked_field(editor, node, options.reason)
        if entry is not None:
            entry["state"] = "blocked"
            entry["lastError"] = options.reason
            state.add_event(session.doc, "node.blocked", at, node=node.id, by=by, data={"reason": options.reason})
    elif action == "reset":
        if current in ("running", "claimed"):
            raise Refused(4, f"{node.id} is {current}; use node fail to send it back")
        targets = [node.id] + ([d for d in state.dependents(plan, [node.id]) if d != node.id] if options.cascade else [])
        touched: List[str] = []
        for target_id in targets:
            target = plan.node(target_id)
            target_state = states[target_id]
            target_entry = state.node_entry(session.doc, target_id) if session.doc is not None else None
            touched_here = False
            if target_state in ("done", "blocked"):
                set_mark(editor, target, " ")
                remove_blocked_fields(editor, target)
                touched_here = True
                if target_entry is not None:
                    target_entry["state"] = "pending"
                    target_entry["finishedAt"] = None
                    target_entry["confirmedBy"] = None
            if target_entry is not None and target_entry["stale"]:
                target_entry["stale"] = False
                touched_here = True
            if touched_here:
                touched.append(target_id)
        if not touched:
            return unchanged(f"node reset {node.id}: nothing to reset")
        cascaded = [t for t in touched if t != node.id]
        if session.doc is not None:
            state.add_event(session.doc, "node.reset", at, node=node.id, by=by, data={"cascade": cascaded})
    else:
        raise Refused(2, f"unknown node action {action}")

    data = {"action": action, "node": None, "planEdited": editor.changed, "cascaded": cascaded}
    change = _finish(session, editor, data, "")
    final_states = state.node_states(change.state_doc) if change.state_doc is not None else None
    view = _node_view(change.plan, final_states or {n.id: n.mark_state for n in change.plan.nodes}, node.id)
    data["node"] = view
    change.text = f"node {action} {node.id}: {current} -> {view['state']}" + (" (plan edited)" if data["planEdited"] else "")
    if cascaded:
        change.text += f"; cascaded: {', '.join(cascaded)}"
    return change


# --------------------------------------------------------------------------- scenario


def record_scenario(
    plan: Plan,
    scenario_id: str,
    status: str,
    evidence: str,
    at: str,
    candidate: Optional[str] = None,
    blocker: Optional[str] = None,
    by: str = "",
) -> Change:
    if plan.legacy:
        raise Refused(2, "scenario commands need a plan with a tier: front matter key")
    if plan.scenario(scenario_id) is None:
        raise Refused(2, f"no scenario {scenario_id} in {plan.relpath()}")
    _no_newline(evidence, candidate, blocker)
    for value in (evidence, candidate, blocker):
        if value is not None and "|" in value:
            raise Refused(2, "evidence, candidate and blocker must not contain |")
    if not evidence.strip():
        raise Refused(2, "--evidence must not be empty")
    row = next((r for r in plan.record_rows if r.id == scenario_id), None)
    if row is None:
        raise Refused(1, f"### Execution record has no row for {scenario_id}", [
            checks.Finding("E-RECORD", f"scenario {scenario_id} has no execution record row", plan.record_line)
        ])
    session = open_session(plan, at, by)
    editor = Editor(plan)
    editor.replace(row.line - 1, f"| {scenario_id} | {status} | {evidence} | {blocker or '—'} |")
    if candidate:
        if plan.candidate_line is not None:
            editor.replace(plan.candidate_line - 1, f"Candidate: {candidate}")
        else:
            editor.insert_after(plan.record_line - 1, f"Candidate: {candidate}")
    effective = candidate or state.candidate_of(plan)
    if session.doc is not None:
        entry = state.scenario_entry(session.doc, scenario_id)
        entry.update({"status": status, "candidate": effective, "evidence": evidence, "recordedAt": at})
        state.add_event(
            session.doc, "scenario.recorded", at, scenario=scenario_id, by=by,
            data={"status": status, "candidate": effective, "evidence": evidence, "blocker": blocker},
        )
    data = {
        "scenario": {"id": scenario_id, "status": status, "candidate": effective, "evidence": evidence, "blocker": blocker},
        "planEdited": editor.changed,
    }
    text = f"scenario {scenario_id}: {status}" + (f" (candidate {effective})" if effective else "")
    return _finish(session, editor, data, text)


def _shown(path: Path, root: Optional[Path]) -> str:
    if root is not None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return str(path)


def _check_destination(path: Path, root: Optional[Path]) -> None:
    shown = _shown(path, root)
    if path.exists() and not path.is_file():
        raise Refused(2, f"cannot write {shown}: it is not a regular file")
    parent = path.parent
    if not parent.is_dir():
        raise Refused(2, f"cannot write {shown}: {_shown(parent, root)} is not a directory")
    if not os.access(str(parent), os.W_OK | os.X_OK):
        raise Refused(2, f"cannot write {shown}: {_shown(parent, root)} is not writable")


def _restore(written: List[Tuple[Path, Optional[bytes]]], root: Optional[Path]) -> List[str]:
    """Put back each replaced file, newest first; return the ones that could not be restored."""
    lost = []
    for path, previous in reversed(written):
        try:
            if previous is None:
                path.unlink()
            else:
                state.write_bytes(path, previous)
        except OSError:
            lost.append(_shown(path, root))
    return lost


def apply(change: Change) -> None:
    """Write the plan, then the state document, then drop plan/ACTIVE.

    Every destination is checked before the first write (``Refused``, exit 2). When a later
    step fails, the files already replaced get their previous bytes back and ``WriteFailed``
    says whether that worked.
    """
    root = change.plan.root if change.plan is not None else None
    writes: List[Tuple[Path, bytes]] = []
    if change.plan_bytes is not None and change.plan_path is not None:
        writes.append((change.plan_path, change.plan_bytes))
    if change.state_doc is not None and change.state_path is not None:
        writes.append((change.state_path, state.encode(change.state_doc)))
    for path, _data in writes:
        _check_destination(path, root)
    if change.remove_active is not None and not change.remove_active.is_file():
        raise Refused(2, f"cannot remove {_shown(change.remove_active, root)}: it is not a regular file")
    written: List[Tuple[Path, Optional[bytes]]] = []
    step = ""
    try:
        for path, data in writes:
            step = f"write {_shown(path, root)}"
            previous = path.read_bytes() if path.exists() else None
            state.write_bytes(path, data)
            written.append((path, previous))
        if change.remove_active is not None:
            step = f"remove {_shown(change.remove_active, root)}"
            change.remove_active.unlink()
    except OSError as exc:
        lost = _restore(written, root)
        outcome = f"could not restore {', '.join(lost)}" if lost else "no file was changed"
        raise WriteFailed(f"cannot {step}: {exc}; {outcome}") from None

