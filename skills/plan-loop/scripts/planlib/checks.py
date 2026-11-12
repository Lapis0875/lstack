"""Plan checks, phase inference, DAG and wave analysis, review digest, status and brief.

Finding codes, their tiers and phases follow the plan-loop plan format reference.
State document checks (``E-STATE-*``) live with the state document code.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .planfile import (
    KNOWN_SECTIONS,
    REVIEWS,
    SCENARIO_FIELDS,
    STATUSES,
    TEAM_TIERS,
    TIERS,
    Node,
    Plan,
)

PHASES = ("draft", "approve", "run", "finish")
REQUIRED_SECTIONS = {
    "base": ("Request", "Goal", "Acceptance criteria", "Scenarios", "Tasks", "Verification", "Plan review"),
    "team": ("Request", "Goal", "Acceptance criteria", "Scenarios", "Team", "Tasks", "Verification", "Plan review"),
    "workflow": (
        "Request",
        "Goal",
        "Acceptance criteria",
        "Scenarios",
        "Team",
        "Workflow",
        "Tasks",
        "Verification",
        "Plan review",
    ),
}
TEAM_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
PLACEHOLDER = re.compile(r"^<[^<>]*>$")
VAGUE_TITLE = re.compile(r"^(investigate|decide|research|explore|tbd)\b", re.IGNORECASE)
WILDCARD = re.compile(r"[*?\[\]{}]")
EXTENSION_GLOB = re.compile(r"^\*\.[^*?\[\]{}]+$")
STATUS_LINE = re.compile(r"^(status|review):")


@dataclass
class Finding:
    code: str
    message: str
    line: Optional[int] = None
    node: Optional[str] = None

    @property
    def severity(self) -> str:
        return "error" if self.code.startswith("E-") else "warning"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
            "node": self.node,
        }


def infer_phase(status: Optional[str]) -> str:
    if status in ("approved", "running"):
        return "run"
    if status == "done":
        return "finish"
    return "draft"


def sort_findings(findings: Iterable[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: (f.line is None, f.line or 0, f.code))


def count(findings: Iterable[Finding]) -> Tuple[int, int]:
    findings = list(findings)
    errors = sum(1 for f in findings if f.severity == "error")
    return errors, len(findings) - errors


# --------------------------------------------------------------------------- digest


def review_digest(plan: Plan) -> str:
    """sha256 of the plan without front matter status/review lines and the Plan review section."""
    drop: Set[int] = set()
    if plan.lines and plan.lines[0].strip() == "---":
        for index in range(1, plan.front_matter_end):
            if STATUS_LINE.match(plan.lines[index]):
                drop.add(index)
    for section in plan.sections:
        if section.name == "Plan review":
            drop.update(range(section.start, section.end))
    kept = [line.rstrip(" \t") for index, line in enumerate(plan.lines) if index not in drop]
    while kept and kept[-1] == "":
        kept.pop()
    payload = "\n".join(kept) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- path patterns


@dataclass(frozen=True)
class PathPattern:
    kind: str  # "file", "tree" or "glob"
    dir: Tuple[str, ...]  # directory segments; for a tree, the tree root segments
    name: Optional[str]  # file name or glob; None for a tree
    raw: str

    @property
    def segments(self) -> Tuple[str, ...]:
        return self.dir if self.name is None else self.dir + (self.name,)


def parse_pattern(raw: str) -> Optional[PathPattern]:
    """A file `a/b.py`, a tree `a/b/` or `a/b/**`, or a last-segment glob `a/*.py`; else None."""
    text = raw.strip()
    if not text or text.startswith("/") or "\\" in text:
        return None
    tree = False
    if text.endswith("/**"):
        text, tree = text[:-3], True
    elif text.endswith("/"):
        text, tree = text[:-1], True
    segments = [segment for segment in text.split("/") if segment != "."]
    if not segments or any(segment in ("", "..") for segment in segments):
        return None
    if tree:
        if any(WILDCARD.search(segment) for segment in segments):
            return None
        return PathPattern("tree", tuple(segments), None, raw)
    directory, name = tuple(segments[:-1]), segments[-1]
    if any(WILDCARD.search(segment) for segment in directory):
        return None
    if WILDCARD.search(name):
        if "**" in name or "{" in name or "}" in name:
            return None
        return PathPattern("glob", directory, name, raw)
    return PathPattern("file", directory, name, raw)


def _under(path: Tuple[str, ...], root: Tuple[str, ...]) -> bool:
    return len(path) >= len(root) and path[: len(root)] == root


def patterns_overlap(a: PathPattern, b: PathPattern) -> bool:
    if a.kind == "tree" or b.kind == "tree":
        tree, other = (a, b) if a.kind == "tree" else (b, a)
        if other.kind == "tree":
            return _under(tree.dir, other.dir) or _under(other.dir, tree.dir)
        if other.kind == "file":
            return _under(other.segments, tree.dir)
        return _under(other.dir, tree.dir)
    if a.dir != b.dir:
        return False
    if a.kind == "file" and b.kind == "file":
        return a.name == b.name
    if a.kind == "glob" and b.kind == "glob":
        if EXTENSION_GLOB.match(a.name or "") and EXTENSION_GLOB.match(b.name or ""):
            return a.name == b.name
        return True
    glob, file = (a, b) if a.kind == "glob" else (b, a)
    return fnmatch.fnmatchcase(file.name or "", glob.name or "")


def pattern_contains(outer: PathPattern, inner: PathPattern) -> bool:
    if outer.kind == "tree":
        return _under(inner.dir if inner.kind != "file" else inner.segments, outer.dir)
    if outer.kind == "file":
        return inner.kind == "file" and inner.segments == outer.segments
    if inner.dir != outer.dir:
        return False
    if inner.kind == "file":
        return fnmatch.fnmatchcase(inner.name or "", outer.name or "")
    return inner.kind == "glob" and inner.name == outer.name


def raw_overlap(a: str, b: str) -> bool:
    pa, pb = parse_pattern(a), parse_pattern(b)
    if pa is None or pb is None:
        return a.strip() == b.strip()
    return patterns_overlap(pa, pb)


def raw_contains(outer: str, inner: str) -> bool:
    po, pi = parse_pattern(outer), parse_pattern(inner)
    if po is None or pi is None:
        return outer.strip() == inner.strip()
    return pattern_contains(po, pi)


def lists_overlap(a: Sequence[str], b: Sequence[str]) -> List[Tuple[str, str]]:
    return [(x, y) for x in a for y in b if raw_overlap(x, y)]


PLAN_TREE = PathPattern("tree", ("plan",), None, "plan/")


def touches_plan_dir(patterns: Sequence[str]) -> bool:
    for raw in patterns:
        parsed = parse_pattern(raw)
        if parsed is not None and patterns_overlap(parsed, PLAN_TREE):
            return True
    return False


# --------------------------------------------------------------------------- graph


def known_after(plan: Plan) -> Dict[str, List[str]]:
    ids = {node.id for node in plan.nodes}
    return {node.id: [a for a in (node.after or []) if a in ids and a != node.id] for node in plan.nodes}


def find_cycles(plan: Plan) -> List[List[str]]:
    """Strongly connected components with more than one node, in file order."""
    graph = known_after(plan)
    order = [node.id for node in plan.nodes]
    index_of: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    components: List[List[str]] = []
    counter = [0]

    def visit(start: str) -> None:
        # Iterative Tarjan.
        work = [(start, iter(graph.get(start, [])))]
        index_of[start] = low[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            current, edges = work[-1]
            advanced = False
            for target in edges:
                if target not in index_of:
                    index_of[target] = low[target] = counter[0]
                    counter[0] += 1
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(graph.get(target, []))))
                    advanced = True
                    break
                if target in on_stack:
                    low[current] = min(low[current], index_of[target])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[current])
            if low[current] == index_of[current]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == current:
                        break
                if len(component) > 1:
                    components.append(sorted(component, key=order.index))

    for node_id in order:
        if node_id not in index_of:
            visit(node_id)
    components.sort(key=lambda component: order.index(component[0]))
    return components


def topological_order(plan: Plan) -> Optional[List[str]]:
    """Kahn's order with file order breaking ties; None when there is a cycle."""
    graph = known_after(plan)
    order = [node.id for node in plan.nodes]
    remaining = {node_id: set(graph[node_id]) for node_id in order}
    result: List[str] = []
    while remaining:
        ready = [node_id for node_id in order if node_id in remaining and not remaining[node_id]]
        if not ready:
            return None
        chosen = ready[0]
        result.append(chosen)
        del remaining[chosen]
        for deps in remaining.values():
            deps.discard(chosen)
    return result


def ancestors(plan: Plan, node_id: str) -> Set[str]:
    graph = known_after(plan)
    seen: Set[str] = set()
    pending = list(graph.get(node_id, []))
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, []))
    return seen


def propose_waves(plan: Plan) -> Optional[List[List[str]]]:
    """Minimum-depth wave layout. None when the after graph has a cycle.

    1. level = 1 + max(level of after), 1 without after.
    2. Same level and overlapping writes: the later node in file order moves down one level.
    3. A gate sharing a level with a work node moves down one level.
    4. File order inside a wave.
    """
    topo = topological_order(plan)
    if topo is None:
        return None
    graph = known_after(plan)
    by_id = {node.id: node for node in plan.nodes}
    order = [node.id for node in plan.nodes]
    floor = {node_id: 1 for node_id in order}
    while True:
        level: Dict[str, int] = {}
        for node_id in topo:
            level[node_id] = max([floor[node_id]] + [level[dep] + 1 for dep in graph[node_id]])
        bump = _first_conflict(by_id, order, level)
        if bump is None:
            break
        floor[bump] = level[bump] + 1
    layout: Dict[int, List[str]] = {}
    for node_id in order:
        layout.setdefault(level[node_id], []).append(node_id)
    return [layout[key] for key in sorted(layout)]


def _first_conflict(by_id: Dict[str, Node], order: List[str], level: Dict[str, int]) -> Optional[str]:
    for current in sorted(set(level.values())):
        members = [node_id for node_id in order if level[node_id] == current]
        for position, later in enumerate(members):
            for earlier in members[:position]:
                if lists_overlap(by_id[earlier].writes or [], by_id[later].writes or []):
                    return later
        gates = [node_id for node_id in members if by_id[node_id].is_gate]
        if gates and len(gates) < len(members):
            return gates[0]
    return None


def declared_waves(plan: Plan) -> List[List[str]]:
    return [list(wave.nodes) for wave in plan.waves]


# --------------------------------------------------------------------------- views


def node_state(node: Node, states: Optional[Dict[str, str]] = None) -> str:
    if states and node.id in states:
        return states[node.id]
    return node.mark_state


def node_views(plan: Plan, states: Optional[Dict[str, str]] = None) -> List[dict]:
    current = {node.id: node_state(node, states) for node in plan.nodes}
    views = []
    for node in plan.nodes:
        role = plan.role(node.owner)
        after = list(node.after or [])
        views.append(
            {
                "id": node.id,
                "title": node.title,
                "mark": node.mark,
                "kind": node.kind,
                "owner": node.owner,
                "ownerKind": role.kind if role is not None else None,
                "after": after,
                "writes": list(node.writes or []),
                "scenarios": list(node.scenarios or []),
                "wave": node.wave,
                "line": node.line,
                "state": current[node.id],
                "ready": current[node.id] == "pending" and all(current.get(dep) == "done" for dep in after),
            }
        )
    return views


def unreachable_nodes(plan: Plan, states: Optional[Dict[str, str]] = None) -> List[str]:
    current = {node.id: node_state(node, states) for node in plan.nodes}
    blocked = {node_id for node_id, state in current.items() if state == "blocked"}
    result = []
    for node in plan.nodes:
        if current[node.id] in ("done", "blocked"):
            continue
        if ancestors(plan, node.id) & blocked:
            result.append(node.id)
    return result


def settled_nodes(plan: Plan, states: Optional[Dict[str, str]] = None) -> Set[str]:
    """Nodes that hold no wave open: done, blocked, or waiting behind a blocked node."""
    current = {node.id: node_state(node, states) for node in plan.nodes}
    settled = {node_id for node_id, state in current.items() if state in ("done", "blocked")}
    settled.update(unreachable_nodes(plan, states))
    return settled


def wave_blockers(plan: Plan, node: Node, states: Optional[Dict[str, str]] = None) -> List[str]:
    """Nodes of earlier waves that keep the wave barrier closed in front of this node.

    A wave that holds only done, blocked and unreachable nodes does not hold back later
    waves: work that does not depend on a blocked node goes on.
    """
    if node.wave is None:
        return []
    settled = settled_nodes(plan, states)
    return [
        other.id
        for other in plan.nodes
        if other.wave is not None and other.wave < node.wave and other.id not in settled
    ]


def wave_progress(plan: Plan, states: Optional[Dict[str, str]] = None) -> Tuple[List[str], Optional[int]]:
    """State of each declared wave (pending, active, closed) and the active wave index.

    A wave is closed when every node in it is done or blocked. The active wave is the first
    wave with a node that is not settled, the same rule ``wave_blockers`` applies, so the
    active wave is the one whose nodes may start.
    """
    current = {node.id: node_state(node, states) for node in plan.nodes}
    settled = settled_nodes(plan, states)
    result: List[str] = []
    active: Optional[int] = None
    for wave in plan.waves:
        closed = bool(wave.nodes) and all(current.get(node_id) in ("done", "blocked") for node_id in wave.nodes)
        is_active = active is None and any(node_id not in settled for node_id in wave.nodes)
        if is_active:
            active = wave.index
        result.append("closed" if closed else ("active" if is_active else "pending"))
    return result, active


def default_state_info(plan: Plan) -> dict:
    declared = plan.state_path is not None
    exists = bool(declared and plan.state_path.is_file())
    return {
        "declared": declared,
        "path": plan.front_matter.get("state") if declared else None,
        "exists": exists,
        "drift": "missing" if declared and not exists else "none",
        "staleNodes": [],
    }


def build_status(
    plan: Plan,
    phase: Optional[str] = None,
    states: Optional[Dict[str, str]] = None,
    state_info: Optional[dict] = None,
) -> dict:
    """The ``data`` object of the ``status`` command."""
    phase = phase or infer_phase(plan.status)
    rows = {}
    for row in plan.coverage:
        rows.setdefault(row.requirement, row)
    requirements = []
    for requirement in plan.requirements:
        row = rows.get(requirement.id)
        requirements.append(
            {
                "id": requirement.id,
                "text": requirement.text,
                "done": requirement.done,
                "happy": list(row.happy) if row else [],
                "other": list(row.other) if row else [],
            }
        )
    scenarios = []
    for scenario in plan.scenarios:
        claimed = [n.id for n in plan.nodes if not n.is_gate and scenario.id in (n.scenarios or [])]
        scenarios.append(
            {
                "id": scenario.id,
                "title": scenario.title,
                "requirements": list(scenario.requirements),
                "executor": scenario.executor,
                "status": plan.scenario_status(scenario.id),
                "claimedBy": claimed,
            }
        )
    views = node_views(plan, states)
    counts = {key: 0 for key in ("pending", "running", "claimed", "done", "blocked")}
    for view in views:
        counts[view["state"]] = counts.get(view["state"], 0) + 1
    waves = []
    wave_states, active = wave_progress(plan, states)
    for position, wave in enumerate(plan.waves):
        waves.append({"index": wave.index, "name": wave.name, "nodes": list(wave.nodes), "state": wave_states[position]})
    return {
        "slug": plan.slug,
        "title": plan.title,
        "team": plan.team,
        "review": plan.review,
        "phase": phase,
        "requirements": requirements,
        "scenarios": scenarios,
        "nodes": views,
        "waves": waves,
        "counts": counts,
        "ready": [view["id"] for view in views if view["ready"]],
        "unreachable": unreachable_nodes(plan, states),
        "activeWave": active,
        "state": state_info if state_info is not None else default_state_info(plan),
        "legacy": {"open": list(plan.open_tasks), "done": plan.done_count} if plan.legacy else None,
    }


# --------------------------------------------------------------------------- brief


def forbidden_paths(plan: Plan, node: Node) -> List[str]:
    """Other nodes' writes that do not overlap this node's writes, then plan/ unless it writes there."""
    own = list(node.writes or [])
    result: List[str] = []
    for other in plan.nodes:
        if other.id == node.id:
            continue
        for pattern in other.writes or []:
            if pattern in result or any(raw_overlap(pattern, mine) for mine in own):
                continue
            result.append(pattern)
    if not touches_plan_dir(own) and "plan/" not in result:
        result.append("plan/")
    return result


def render_brief(plan: Plan, node: Node) -> str:
    role = plan.role(node.owner)
    lines: List[str] = []
    add = lines.append
    add(f"# Brief: {node.id} — {node.title}")
    add("")
    add(f"Plan: {plan.relpath()} (tier {plan.tier}, team {plan.team or '-'})")
    add(f"Node: {node.id} — {node.title}")
    add(f"Kind: {node.kind}")
    owner = node.owner or "-"
    add(f"Owner: {owner}" + (f" ({role.kind}, host agent {role.host or '-'})" if role else ""))
    add(f"Wave: {node.wave if node.wave is not None else '-'}")
    add(f"After: {', '.join(node.after) if node.after else '—'}")
    add("")
    add("## Goal")
    add("")
    add(plan.section_body("Goal") or "(none)")
    add("")
    add("## Contracts")
    add("")
    add(plan.section_body("Contracts") or "(none)")
    add("")
    add("## Your task")
    add("")
    add(f"- writes (allowed paths): {_ticked(node.writes)}")
    for key in ("consumes", "produces"):
        if node.has(key):
            add(f"- {key}: {_ticked(getattr(node, key))}")
    for key in ("done-when", "check", "refs", "gate"):
        if node.has(key):
            add(f"- {key}: {node.fields[key]}")
    add(f"- scenarios: {', '.join(node.scenarios) if node.scenarios else '—'}")
    add("")
    writers = [
        other
        for other in plan.nodes
        if other.wave is not None and other.wave == node.wave and not other.is_gate
    ]
    if node.is_gate:
        add("Run on the frozen candidate only. Do not edit any file.")
    elif len(writers) > 1:
        add(
            f"Wave {node.wave} has {len(writers)} writers: do not run builds or tests while writing; "
            "the orchestrator runs each node's check when the wave closes."
        )
    else:
        add("You are the only writer in this wave: run the check yourself when your change is complete.")
    add("")
    add("## Scenarios")
    add("")
    linked = [plan.scenario(scenario_id) for scenario_id in node.scenarios or []]
    linked = [scenario for scenario in linked if scenario is not None]
    if not linked:
        add("(none)")
    for scenario in linked:
        add(scenario.text)
        add("")
    requirement_ids = []
    for scenario in linked:
        for requirement_id in scenario.requirements:
            if requirement_id not in requirement_ids:
                requirement_ids.append(requirement_id)
    if requirement_ids:
        add("Requirements behind these scenarios:")
        for requirement in plan.requirements:
            if requirement.id in requirement_ids:
                add(f"- {requirement.id} {requirement.text}")
        add("")
    add("## Forbidden paths")
    add("")
    add("Do not create, modify or delete anything matching these paths:")
    for pattern in forbidden_paths(plan, node):
        add(f"- `{pattern}`")
    add("")
    add("## Report")
    add("")
    add("Return:")
    add("1. Status: done, failed or blocked, with the reason.")
    add("2. Every file you created or changed.")
    add("3. Every command you ran and its actual output (exit code, summary lines).")
    add("4. Deviations from the contracts or this brief, and open questions. Write `none` if there are none.")
    return "\n".join(lines).rstrip("\n") + "\n"


def _ticked(patterns: Optional[Sequence[str]]) -> str:
    if not patterns:
        return "—"
    return ", ".join(f"`{pattern}`" for pattern in patterns)


# --------------------------------------------------------------------------- checks


def run_checks(plan: Plan, phase: str) -> List[Finding]:
    findings: List[Finding] = []

    def add(code: str, message: str, line: Optional[int] = None, node: Optional[str] = None) -> None:
        findings.append(Finding(code=code, message=message, line=line, node=node))

    _check_slug(plan, add)
    if plan.legacy:
        add("W-LEGACY", "plan has no tier: front matter key; only legacy task counting applies", 1 if plan.lines else None)
        if phase == "finish" and plan.open_tasks:
            add("E-FINISH-OPEN", f"{len(plan.open_tasks)} open task(s) remain; first: {plan.open_tasks[0]}")
        return sort_findings(findings)

    _check_front_matter(plan, add)
    _check_sections(plan, add)
    _check_requirements(plan, add)
    _check_scenarios(plan, add)
    _check_coverage(plan, add)
    _check_record(plan, phase, add)
    _check_tasks(plan, phase, add)
    if plan.tier in TEAM_TIERS:
        _check_team(plan, phase, add)
        _check_scope(plan, add)
        _check_dag(plan, add)
        _check_gates(plan, add)
    if plan.tier == "workflow":
        _check_brief_fields(plan, add)
    if phase == "approve":
        _check_review(plan, add)
    if phase in ("run", "finish") and plan.review not in ("passed", "waived"):
        add(
            "E-REVIEW-STATE",
            f"front matter review is {plan.review or 'missing'}; an approved plan needs passed or waived",
            plan.front_matter_lines.get("review"),
        )
    if phase == "finish":
        _check_finish(plan, add)
    return sort_findings(findings)


Add = Callable[..., None]


def _check_slug(plan: Plan, add: Add) -> None:
    slug = plan.front_matter.get("slug")
    if slug is not None and slug != plan.slug:
        add("W-FM-SLUG", f"front matter slug '{slug}' differs from the file name '{plan.slug}'", plan.front_matter_lines.get("slug"))


def _check_front_matter(plan: Plan, add: Add) -> None:
    fm = plan.front_matter
    where = plan.front_matter_lines
    if plan.status not in STATUSES:
        add("E-FM-KEY", f"status must be one of {', '.join(STATUSES)}", where.get("status"))
    if plan.tier not in TIERS:
        add("E-FM-KEY", f"tier must be one of {', '.join(TIERS)}", where.get("tier"))
    if fm.get("review") not in REVIEWS:
        add("E-FM-KEY", f"review must be one of {', '.join(REVIEWS)}", where.get("review"))
    if plan.tier in TEAM_TIERS and not fm.get("team"):
        add("E-FM-KEY", f"tier {plan.tier} needs a team: key", where.get("tier"))
    if fm.get("team") and not TEAM_NAME.match(fm["team"]):
        add("E-FM-KEY", "team must match [a-z][a-z0-9-]*", where.get("team"))
    state = fm.get("state")
    if plan.tier == "workflow" and not state:
        add("E-FM-KEY", "tier workflow needs state: plan/<slug>.state.json", where.get("tier"))
    if plan.tier == "base" and "state" in fm:
        add("E-FM-KEY", "tier base must not declare state:", where.get("state"))
    if state and state != f"plan/{plan.slug}.state.json":
        add("E-FM-KEY", f"state must be plan/{plan.slug}.state.json", where.get("state"))


def _check_sections(plan: Plan, add: Add) -> None:
    present = [section.name for section in plan.sections]
    for name in REQUIRED_SECTIONS.get(plan.tier or "", ()):
        if name not in present:
            add("E-SECTION", f"missing required section ## {name}")
    seen: Dict[str, int] = {}
    for section in plan.sections:
        if section.name not in KNOWN_SECTIONS:
            continue
        if section.name in seen:
            add("E-SECTION", f"section ## {section.name} appears twice (first on line {seen[section.name]})", section.start + 1)
        else:
            seen[section.name] = section.start + 1


def _check_requirements(plan: Plan, add: Add) -> None:
    if not plan.requirements:
        section = plan.section("Acceptance criteria")
        add("E-REQ-NONE", "## Acceptance criteria has no `- [ ] ID text` requirement line", section.start + 1 if section else None)
    seen: Dict[str, int] = {}
    for requirement in plan.requirements:
        if requirement.id in seen:
            add("E-REQ-DUP", f"requirement {requirement.id} is listed twice (first on line {seen[requirement.id]})", requirement.line)
        else:
            seen[requirement.id] = requirement.line


def _check_scenarios(plan: Plan, add: Add) -> None:
    if not plan.scenarios:
        section = plan.section("Scenarios")
        add("E-SCEN-NONE", "## Scenarios has no `### AT-NN — title` scenario", section.start + 1 if section else None)
    seen: Dict[str, int] = {}
    requirement_ids = {requirement.id for requirement in plan.requirements}
    for scenario in plan.scenarios:
        if scenario.id in seen:
            add("E-SCEN-DUP", f"scenario {scenario.id} appears twice (first on line {seen[scenario.id]})", scenario.line)
        else:
            seen[scenario.id] = scenario.line
        for name in SCENARIO_FIELDS:
            line = scenario.field_lines.get(name, scenario.line)
            if name not in scenario.fields:
                add("E-SCEN-FIELD", f"scenario {scenario.id} is missing field '{name}'", scenario.line)
                continue
            value = scenario.fields[name].strip()
            if not value:
                add("E-SCEN-FIELD", f"scenario {scenario.id} field '{name}' is empty", line)
            elif PLACEHOLDER.match(value):
                add("E-SCEN-FIELD", f"scenario {scenario.id} field '{name}' is still a placeholder", line)
            elif name == "Owners" and ("<" in value or scenario.executor is None):
                add(
                    "E-SCEN-FIELD",
                    f"scenario {scenario.id} Owners must read `implementer <role>; executor <role>`",
                    line,
                )
            elif name == "Requirement" and not scenario.requirements_valid:
                add("E-SCEN-FIELD", f"scenario {scenario.id} Requirement must be a comma list of requirement IDs", line)
        for requirement_id in scenario.requirements:
            if requirement_id not in requirement_ids:
                add(
                    "E-SCEN-REQ",
                    f"scenario {scenario.id} names requirement {requirement_id}, which is not in ## Acceptance criteria",
                    scenario.field_lines.get("Requirement", scenario.line),
                )


def _check_coverage(plan: Plan, add: Add) -> None:
    requirement_ids = {requirement.id for requirement in plan.requirements}
    scenarios = {scenario.id: scenario for scenario in plan.scenarios}
    rows: Dict[str, object] = {}
    for row in plan.coverage:
        if row.requirement in rows:
            add("E-COVERAGE-MAP", f"coverage table lists requirement {row.requirement} twice", row.line)
            continue
        rows[row.requirement] = row
        if row.requirement not in requirement_ids:
            add("E-COVERAGE-MAP", f"coverage row names requirement {row.requirement}, which is not in ## Acceptance criteria", row.line)
        for scenario_id in row.happy + row.other:
            scenario = scenarios.get(scenario_id)
            if scenario is None:
                add("E-COVERAGE-MAP", f"coverage row {row.requirement} names {scenario_id}, which has no scenario", row.line)
            elif row.requirement not in scenario.requirements:
                add(
                    "E-COVERAGE-MAP",
                    f"coverage row {row.requirement} lists {scenario_id}, but {scenario_id} Requirement is "
                    f"{', '.join(scenario.requirements) or 'empty'}",
                    row.line,
                )
    for requirement in plan.requirements:
        row = rows.get(requirement.id)
        if row is None:
            add("E-COVERAGE-HAPPY", f"requirement {requirement.id} has no row in the coverage table", requirement.line)
        elif not row.happy:
            add("E-COVERAGE-HAPPY", f"requirement {requirement.id} has no happy-path scenario in the coverage table", row.line)
    for scenario in plan.scenarios:
        listed = [row for row in rows.values() if scenario.id in row.happy + row.other]
        if not listed:
            add("E-COVERAGE-MAP", f"scenario {scenario.id} is not in any coverage table row", scenario.line)
            continue
        for requirement_id in scenario.requirements:
            row = rows.get(requirement_id)
            if row is not None and scenario.id not in row.happy + row.other:
                add(
                    "E-COVERAGE-MAP",
                    f"scenario {scenario.id} names requirement {requirement_id}, but row {requirement_id} does not list it",
                    row.line,
                )


def _check_record(plan: Plan, phase: str, add: Add) -> None:
    if plan.record_line is None:
        section = plan.section("Scenarios")
        add("E-RECORD", "## Scenarios has no ### Execution record", section.start + 1 if section else None)
        return
    ids = {scenario.id for scenario in plan.scenarios}
    rows_per_id: Dict[str, int] = {}
    for row in plan.record_rows:
        rows_per_id[row.id] = rows_per_id.get(row.id, 0) + 1
        if not row.valid:
            add("E-RECORD", f"execution record row {row.id} has status '{row.status}'; use NOT_RUN, PASS, FAIL or BLOCKED", row.line)
        if row.id not in ids:
            add("E-RECORD", f"execution record row {row.id} has no scenario", row.line)
        elif row.valid and row.status != "NOT_RUN" and phase in ("draft", "approve"):
            add("E-RECORD", f"execution record row {row.id} is {row.status} before the plan is approved", row.line)
    for scenario in plan.scenarios:
        rows = rows_per_id.get(scenario.id, 0)
        if rows != 1:
            add("E-RECORD", f"scenario {scenario.id} has {rows} execution record rows; it needs exactly 1", plan.record_line)


def _check_tasks(plan: Plan, phase: str, add: Add) -> None:
    if not plan.nodes:
        section = plan.section("Tasks")
        add("E-TASK-NONE", "## Tasks has no `- [ ] ID title` node", section.start + 1 if section else None)
    for code, line, message in plan.task_issues:
        add(code, message, line)
    seen: Dict[str, int] = {}
    requirement_ids = {requirement.id for requirement in plan.requirements}
    known = {scenario.id for scenario in plan.scenarios}
    team_like = plan.tier in TEAM_TIERS
    for node in plan.nodes:
        if node.id in seen:
            add("E-TASK-ID", f"node {node.id} appears twice (first on line {seen[node.id]})", node.line, node.id)
        else:
            seen[node.id] = node.line
        if node.id in requirement_ids:
            add("E-TASK-ID", f"node ID {node.id} is also a requirement ID", node.line, node.id)
        if phase in ("draft", "approve") and VAGUE_TITLE.match(node.title):
            add("W-TASK-VAGUE", f"node {node.id} title starts with a vague verb; name the concrete change", node.line, node.id)
        for line, message in node.issues:
            add("E-NODE-FIELD", message, line, node.id)
        if team_like:
            required = ("owner", "after", "scenarios") if node.is_gate else ("owner", "after", "writes", "scenarios")
            for key in required:
                if not node.has(key):
                    add("E-NODE-FIELD", f"node {node.id} is missing field '{key}'", node.line, node.id)
        if not node.scenarios_all:
            for scenario_id in node.scenarios or []:
                if scenario_id not in known:
                    add(
                        "E-NODE-FIELD",
                        f"node {node.id} names scenario {scenario_id}, which does not exist",
                        node.field_lines.get("scenarios", node.line),
                        node.id,
                    )


def _check_team(plan: Plan, phase: str, add: Add) -> None:
    section = plan.section("Team")
    team_line = section.start + 1 if section else None
    orchestrators = [role for role in plan.team_roles if role.kind == "orchestrator"]
    if len(orchestrators) != 1:
        add("E-TEAM-ROLE", f"## Team needs exactly one orchestrator role, found {len(orchestrators)}", team_line)
    seen: Dict[str, int] = {}
    for role in plan.team_roles:
        if role.name in seen:
            add("E-TEAM-ROLE", f"role {role.name} is listed twice (first on line {seen[role.name]})", role.line)
        else:
            seen[role.name] = role.line
    for line, message in plan.role_issues:
        add("E-TEAM-ROLE", message, line)
    for node in plan.nodes:
        if node.owner is None:
            continue
        role = plan.role(node.owner)
        line = node.field_lines.get("owner", node.line)
        if role is None:
            add("E-TEAM-ROLE", f"node {node.id} owner '{node.owner}' is not a role in ## Team", line, node.id)
            continue
        if not node.is_gate and role.kind not in ("writer", "orchestrator"):
            add("E-NODE-KIND", f"work node {node.id} owner '{node.owner}' has Kind {role.kind}; use a writer", line, node.id)
        if node.gate == "test" and role.kind != "executor":
            add("E-GATE-OWNER", f"test gate {node.id} owner '{node.owner}' has Kind {role.kind}; it needs an executor", line, node.id)
        if node.gate == "review" and role.kind != "reviewer":
            add("E-GATE-OWNER", f"review gate {node.id} owner '{node.owner}' has Kind {role.kind}; it needs a reviewer", line, node.id)
    for node in plan.nodes:
        if not node.is_gate and phase in ("draft", "approve") and node.has("scenarios") and not node.scenarios_all and node.scenarios == []:
            add("W-NODE-NOSCEN", f"work node {node.id} claims no scenario", node.field_lines.get("scenarios", node.line), node.id)
    claimed: Set[str] = set()
    for node in plan.nodes:
        if not node.is_gate:
            claimed.update(node.scenarios or [])
    for scenario in plan.scenarios:
        if scenario.id not in claimed:
            add("E-SCEN-UNCLAIMED", f"scenario {scenario.id} is not in any work node's scenarios", scenario.line)
        if scenario.executor is None:
            continue
        role = plan.role(scenario.executor)
        line = scenario.field_lines.get("Owners", scenario.line)
        if role is None:
            add("E-SCEN-EXECUTOR", f"scenario {scenario.id} executor '{scenario.executor}' is not a role in ## Team", line)
        elif role.kind != "executor":
            add("E-SCEN-EXECUTOR", f"scenario {scenario.id} executor '{scenario.executor}' has Kind {role.kind}; it needs Kind executor", line)


def _check_scope(plan: Plan, add: Add) -> None:
    for node in plan.nodes:
        for key in ("writes", "consumes", "produces"):
            for pattern in getattr(node, key) or []:
                if parse_pattern(pattern) is None:
                    add(
                        "E-SCOPE-PATTERN",
                        f"node {node.id} {key} pattern `{pattern}` is not a file, a tree (dir/ or dir/**) or a last-segment glob",
                        node.field_lines.get(key, node.line),
                        node.id,
                    )
    nodes = plan.nodes
    for position, later in enumerate(nodes):
        for earlier in nodes[:position]:
            pairs = lists_overlap(earlier.writes or [], later.writes or [])
            if not pairs:
                continue
            shown = ", ".join(f"`{a}` / `{b}`" for a, b in pairs)
            line = later.field_lines.get("writes", later.line)
            if earlier.wave is not None and earlier.wave == later.wave:
                add("E-SCOPE-OVERLAP", f"nodes {earlier.id} and {later.id} in wave {later.wave} write overlapping paths: {shown}", line, later.id)
            elif earlier.wave != later.wave and earlier.owner and later.owner and earlier.owner != later.owner:
                add(
                    "E-SCOPE-OWNER",
                    f"nodes {earlier.id} ({earlier.owner}) and {later.id} ({later.owner}) write overlapping paths: {shown}; "
                    "one path has one writer",
                    line,
                    later.id,
                )
    for node in nodes:
        role = plan.role(node.owner)
        if role is not None and role.kind != "orchestrator" and touches_plan_dir(node.writes or []):
            add("E-SCOPE-PLAN", f"node {node.id} owner '{node.owner}' writes under plan/; only the orchestrator writes there", node.field_lines.get("writes", node.line), node.id)


def _check_dag(plan: Plan, add: Add) -> None:
    ids = {node.id for node in plan.nodes}
    waves = {node.id: node.wave for node in plan.nodes}
    for node in plan.nodes:
        line = node.field_lines.get("after", node.line)
        for dep in node.after or []:
            if dep == node.id:
                add("E-DAG-UNKNOWN", f"node {node.id} lists itself in after", line, node.id)
            elif dep not in ids:
                add("E-DAG-UNKNOWN", f"node {node.id} depends on unknown node {dep}", line, node.id)
            elif node.wave is not None and waves[dep] is not None and waves[dep] >= node.wave:
                add(
                    "E-WAVE-ORDER",
                    f"node {node.id} (wave {node.wave}) depends on {dep} (wave {waves[dep]}); a dependency must be in an earlier wave",
                    line,
                    node.id,
                )
    by_id = {node.id: node for node in plan.nodes}
    for component in find_cycles(plan):
        first = by_id[component[0]]
        add("E-DAG-CYCLE", f"after graph has a cycle through {', '.join(component)}", first.line, first.id)
    for node in plan.nodes:
        if node.wave is None:
            add("E-WAVE-MISSING", f"node {node.id} is not under a ### Wave N heading", node.line, node.id)
    for expected, wave in enumerate(plan.waves, start=1):
        if wave.index != expected:
            add("E-WAVE-MISSING", f"wave numbers must run 1, 2, 3…; found Wave {wave.index} where Wave {expected} belongs", wave.line)
        if not wave.nodes:
            add("E-WAVE-MISSING", f"Wave {wave.index} has no node", wave.line)


def _check_gates(plan: Plan, add: Add) -> None:
    for node in plan.nodes:
        if node.is_gate and node.writes:
            add("E-GATE-WRITES", f"gate {node.id} must have writes: —", node.field_lines.get("writes", node.line), node.id)
    for wave in plan.waves:
        members = [plan.node(node_id) for node_id in wave.nodes]
        gates = [node for node in members if node is not None and node.is_gate]
        work = [node for node in members if node is not None and not node.is_gate]
        if gates and work:
            add(
                "E-GATE-WAVE",
                f"Wave {wave.index} mixes gates ({', '.join(n.id for n in gates)}) and work nodes ({', '.join(n.id for n in work)})",
                wave.line,
                gates[0].id,
            )
    work_waves = [node.wave for node in plan.nodes if not node.is_gate and node.wave is not None]
    last_work = max(work_waves) if work_waves else 0
    finals = [
        node
        for node in plan.nodes
        if node.gate == "test" and node.scenarios_all and node.wave is not None and node.wave > last_work
    ]
    tasks = plan.section("Tasks")
    tasks_line = tasks.start + 1 if tasks else None
    if not finals:
        add("E-GATE-FINAL-TEST", f"no `gate: test` node with `scenarios: all` after the last work wave ({last_work})", tasks_line)
        return
    final_wave = max(node.wave for node in finals)
    if not any(node.gate == "review" and node.wave is not None and node.wave > final_wave for node in plan.nodes):
        add("E-GATE-FINAL-REVIEW", f"no `gate: review` node after the final test gate in wave {final_wave}", tasks_line)


def _check_brief_fields(plan: Plan, add: Add) -> None:
    for node in plan.nodes:
        if node.is_gate:
            continue
        for key in ("consumes", "produces", "done-when", "check"):
            value = node.fields.get(key, "").strip()
            if not node.has(key) or not value or (key in ("done-when", "check") and value in ("—", "-")):
                add("E-BRIEF-FIELD", f"workflow node {node.id} needs a non-empty '{key}' field", node.line, node.id)
        for pattern in node.produces or []:
            if not any(raw_contains(write, pattern) for write in node.writes or []):
                add(
                    "E-BRIEF-PRODUCES",
                    f"node {node.id} produces `{pattern}`, which is outside its writes",
                    node.field_lines.get("produces", node.line),
                    node.id,
                )
        if not node.consumes:
            continue
        upstream = ancestors(plan, node.id)
        produced = [p for other in plan.nodes if other.id in upstream for p in other.produces or []]
        for pattern in node.consumes:
            if any(raw_overlap(pattern, p) for p in produced) or _exists(plan, pattern):
                continue
            add(
                "E-BRIEF-CONSUMES",
                f"node {node.id} consumes `{pattern}`, which no upstream node produces and the repository does not have",
                node.field_lines.get("consumes", node.line),
                node.id,
            )


def _exists(plan: Plan, raw: str) -> bool:
    parsed = parse_pattern(raw)
    if parsed is None:
        return False
    base = plan.root.joinpath(*parsed.dir) if parsed.dir else plan.root
    if parsed.kind == "tree":
        return base.is_dir()
    if parsed.kind == "file":
        return (base / (parsed.name or "")).exists()
    return base.is_dir() and any(True for _ in base.glob(parsed.name or ""))


def _check_review(plan: Plan, add: Add) -> None:
    if plan.waivers:
        return
    section = plan.section("Plan review")
    if not plan.review_rounds:
        add("E-REVIEW-MISSING", "## Plan review has no review round and no `Waived by user` line", section.start + 1 if section else None)
        return
    last = plan.review_rounds[-1]
    if last.verdict == "REVISE":
        add("E-REVIEW-VERDICT", f"last review round {last.number} verdict is REVISE", last.line)
    if last.digest == "unavailable":
        add("W-REVIEW-NODIGEST", f"last review round {last.number} has no digest; the plan may have changed since", last.line)
    else:
        current = review_digest(plan)[:12]
        if last.digest != current:
            add(
                "E-REVIEW-STALE",
                f"last review round {last.number} reviewed digest {last.digest}; the plan now has digest {current}",
                last.line,
            )
    if last.mode == "self":
        add("W-REVIEW-SELF", f"last review round {last.number} is a self review", last.line)
    for review_round in plan.review_rounds:
        for finding in review_round.findings:
            if finding.status == "open":
                add("E-REVIEW-OPEN", f"review finding {finding.id} [{finding.code}] is still open", finding.line)


def _check_finish(plan: Plan, add: Add) -> None:
    for node in plan.nodes:
        if node.mark in (" ", "!"):
            state = "blocked" if node.mark == "!" else "open"
            add("E-FINISH-OPEN", f"node {node.id} is still {state}", node.line, node.id)
    for scenario in plan.scenarios:
        status = plan.scenario_status(scenario.id)
        if status != "PASS":
            add("E-FINISH-SCEN", f"scenario {scenario.id} is {status}; finishing needs PASS", scenario.line)
