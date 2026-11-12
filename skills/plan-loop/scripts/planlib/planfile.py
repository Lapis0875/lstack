"""Locate the active plan and parse plan files. This is the only plan parser.

A plan whose front matter has no ``tier`` key is a legacy plan. Its status and task
counts are computed exactly as the original Codex hook did
(``codex/plan-loop/hooks/plan_state.py`` at commit 7aa60fc): no fences, no grammar.

A tier plan (``tier: base|team|workflow``) is parsed with the plan grammar. Lines
inside fenced code blocks are ignored by every rule. A UTF-8 BOM is dropped and
``\\r\\n`` / ``\\r`` line ends are read as ``\\n``; line numbers are 1-based and match
the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Legacy counting, unchanged from the original hook.
OPEN_TASK = re.compile(r"^\s*- \[ \] (.+)$")
DONE_TASK = re.compile(r"^\s*- \[x\] ", re.IGNORECASE)
STATUS = re.compile(r"^status:\s*(\S+)\s*$")

TIERS = ("base", "team", "workflow")
TEAM_TIERS = ("team", "workflow")
STATUSES = ("planning", "approved", "running", "done", "abandoned")
REVIEWS = ("pending", "passed", "waived")
ROLE_KINDS = ("orchestrator", "writer", "executor", "reviewer")
SCENARIO_FIELDS = (
    "Requirement",
    "Preconditions / data",
    "Actions",
    "Expected outcome",
    "Verification",
    "Owners",
    "Evidence required",
)
SCENARIO_STATUSES = ("NOT_RUN", "PASS", "FAIL", "BLOCKED")
NODE_FIELD_KEYS = (
    "owner",
    "after",
    "writes",
    "files",
    "scenarios",
    "gate",
    "refs",
    "check",
    "consumes",
    "produces",
    "done-when",
    "evidence",
    "blocked",
)
FIELD_ALIASES = {"files": "writes"}
REPEATABLE_FIELDS = ("evidence",)
KNOWN_SECTIONS = (
    "Request",
    "Goal",
    "Acceptance criteria",
    "Won't",
    "References",
    "Contracts",
    "Scenarios",
    "Team",
    "Workflow",
    "Tasks",
    "Verification",
    "Risks and open questions",
    "Plan review",
    "Changes",
)
NONE_MARKERS = ("—", "-")

FM_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*$")
H2 = re.compile(r"^## (.+?)\s*$")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
REQUIREMENT = re.compile(r"^- \[( |x|X)\] ([A-Z]{1,3}\d{1,3})\s+(\S.*)$")
REQUIREMENT_ID = re.compile(r"^[A-Z]{1,3}\d{1,3}$")
COVERAGE_ROW = re.compile(r"^\|\s*([A-Z]{1,3}\d{1,3})\b[^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$")
SCENARIO_REF = re.compile(r"AT-\d{2,3}")
SCENARIO_ID = re.compile(r"^AT-\d{2,3}$")
SCENARIO_HEAD = re.compile(r"^### (AT-\d{2,3}) (?:—|-) (\S.*)$")
SCENARIO_FIELD = re.compile(
    r"^- (Requirement|Preconditions / data|Actions|Expected outcome|Verification|Owners|Evidence required):\s*(.*)$"
)
OWNERS = re.compile(r"^implementer\s+([^;]+);\s*executor\s+(.+)$")
RECORD_HEAD = "### Execution record"
CANDIDATE = re.compile(r"^Candidate:\s*(.+)$")
RECORD_ROW = re.compile(r"^\|\s*(AT-\d{2,3})\s*\|\s*(NOT_RUN|PASS|FAIL|BLOCKED)\s*\|([^|]*)\|([^|]*)\|\s*$")
RECORD_ROW_LOOSE = re.compile(r"^\|\s*(AT-\d{2,3})\s*\|")
ROLE_ROW = re.compile(
    r"^\|\s*`?([a-z][a-z0-9-]*)`?\s*\|\s*(orchestrator|writer|executor|reviewer)\s*\|([^|]*)\|([^|]*)\|\s*$"
)
ROLE_ROW_LOOSE = re.compile(r"^\|\s*`?([a-z][a-z0-9-]*)`?\s*\|")
WAVE_HEAD = re.compile(r"^### Wave (\d+)(?:: (.+))?$")
PHASE_HEAD = re.compile(r"^### Phase (\d+)(?:: (.+))?$")
NODE_HEAD = re.compile(r"^- \[( |x|X|!)\] ([A-Z]{1,3}\d{1,3}[a-z]?)\s+(\S.*)$")
NODE_ID = re.compile(r"^[A-Z]{1,3}\d{1,3}[a-z]?$")
CHECKBOX_COL0 = re.compile(r"^- \[[ xX!]\]")
CHECKBOX_INDENTED = re.compile(r"^\s+- \[[ xX!]\]")
_FIELD_KEY_PATTERN = "|".join(re.escape(key) for key in NODE_FIELD_KEYS)
NODE_FIELD = re.compile(r"^ {2,}- (" + _FIELD_KEY_PATTERN + r"):\s*(.*)$")
INLINE_FIELD = re.compile(r"^(" + _FIELD_KEY_PATTERN + r"):\s*(.*)$")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
BACKTICK_LIST = re.compile(r"^`[^`]+`(?:\s*,\s*`[^`]+`)*$")
BACKTICK_ITEM = re.compile(r"`([^`]+)`")
POLICY = re.compile(r"^- (max-parallel|max-attempts):\s*(\d+)$")
ROUND = re.compile(
    r"^- Round (\d+) — reviewer: (.+?) — mode: (independent|self) — "
    r"digest: ([0-9a-f]{12}|unavailable) — verdict: (PASS|REVISE)$"
)
REVIEW_FINDING = re.compile(r"^ {2,}- (F\d+) \[(B[1-6])\] (.+?) — status: (open|fixed|rejected|waived)(.*)$")
WAIVER = re.compile(r"^- Waived by user: (\d{4}-\d{2}-\d{2}) — (.+)$")


@dataclass
class Section:
    name: str
    start: int  # 0-based index of the "## " line
    end: int  # 0-based index one past the last line of the section


@dataclass
class Requirement:
    id: str
    text: str
    done: bool
    line: int


@dataclass
class CoverageRow:
    requirement: str
    happy: List[str]
    other: List[str]
    not_applicable: str
    line: int


@dataclass
class Scenario:
    id: str
    title: str
    line: int
    end: int  # 1-based line number of the last line of the block
    fields: Dict[str, str] = field(default_factory=dict)
    field_lines: Dict[str, int] = field(default_factory=dict)
    requirements: List[str] = field(default_factory=list)
    requirements_valid: bool = True
    implementer: Optional[str] = None
    executor: Optional[str] = None
    text: str = ""


@dataclass
class RecordRow:
    id: str
    status: str
    valid: bool
    evidence: str
    blocker: str
    line: int


@dataclass
class Role:
    name: str
    kind: str
    host: str
    notes: str
    line: int


@dataclass
class Wave:
    index: int
    name: Optional[str]
    line: int
    nodes: List[str] = field(default_factory=list)


@dataclass
class Node:
    id: str
    title: str
    mark: str  # " ", "x" or "!"
    line: int
    end: int  # 1-based line number of the last line of the block
    wave: Optional[int] = None
    fields: Dict[str, str] = field(default_factory=dict)  # canonical key -> raw value
    field_lines: Dict[str, int] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    issues: List[Tuple[int, str]] = field(default_factory=list)  # value grammar problems
    owner: Optional[str] = None
    after: Optional[List[str]] = None
    writes: Optional[List[str]] = None
    scenarios: Optional[List[str]] = None
    scenarios_all: bool = False
    gate: Optional[str] = None
    consumes: Optional[List[str]] = None
    produces: Optional[List[str]] = None

    @property
    def kind(self) -> str:
        if self.gate == "test":
            return "gate-test"
        if self.gate == "review":
            return "gate-review"
        return "work"

    @property
    def is_gate(self) -> bool:
        return self.gate in ("test", "review")

    @property
    def mark_state(self) -> str:
        return {"x": "done", "!": "blocked"}.get(self.mark, "pending")

    def has(self, key: str) -> bool:
        return key in self.fields


@dataclass
class ReviewFinding:
    id: str
    code: str
    text: str
    status: str
    rest: str
    line: int


@dataclass
class ReviewRound:
    number: int
    reviewer: str
    mode: str
    digest: str
    verdict: str
    line: int
    findings: List[ReviewFinding] = field(default_factory=list)


@dataclass
class Waiver:
    date: str
    reason: str
    line: int


@dataclass
class Plan:
    root: Path
    path: Path
    status: str
    tier: Optional[str] = None
    team: Optional[str] = None
    review: Optional[str] = None
    state_path: Optional[Path] = None
    requirements: List[Requirement] = field(default_factory=list)
    scenarios: List[Scenario] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)
    team_roles: List[Role] = field(default_factory=list)
    review_rounds: List[ReviewRound] = field(default_factory=list)
    coverage: List[CoverageRow] = field(default_factory=list)
    candidate: Optional[str] = None
    open_tasks: List[str] = field(default_factory=list)
    done_count: int = 0
    # Everything below supports checks, rendering and editing.
    title: str = ""
    front_matter: Dict[str, str] = field(default_factory=dict)
    front_matter_lines: Dict[str, int] = field(default_factory=dict)
    front_matter_end: int = 0  # index of the closing "---" (0 when there is no front matter)
    lines: List[str] = field(default_factory=list)  # BOM dropped, line ends normalized
    fenced: List[bool] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    waves: List[Wave] = field(default_factory=list)
    waivers: List[Waiver] = field(default_factory=list)
    policy: Dict[str, int] = field(default_factory=dict)
    record_line: Optional[int] = None  # line of "### Execution record"
    record_rows: List[RecordRow] = field(default_factory=list)
    candidate_line: Optional[int] = None
    role_issues: List[Tuple[int, str]] = field(default_factory=list)
    task_issues: List[Tuple[str, int, str]] = field(default_factory=list)  # (code, line, message)
    newline: str = "\n"  # dominant line end of the file on disk
    bom: bool = False
    raw: bytes = field(default=b"", repr=False)  # the file bytes this plan was parsed from

    @property
    def legacy(self) -> bool:
        return self.tier is None

    @property
    def slug(self) -> str:
        return self.path.stem

    def section(self, name: str) -> Optional[Section]:
        for section in self.sections:
            if section.name == name:
                return section
        return None

    def section_body(self, name: str) -> str:
        """Raw text of a section without its heading; fenced lines kept, edges trimmed."""
        section = self.section(name)
        if section is None:
            return ""
        return "\n".join(self.lines[section.start + 1 : section.end]).strip("\n")

    def node(self, node_id: str) -> Optional[Node]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def scenario(self, scenario_id: str) -> Optional[Scenario]:
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        return None

    def role(self, name: Optional[str]) -> Optional[Role]:
        for role in self.team_roles:
            if role.name == name:
                return role
        return None

    def scenario_status(self, scenario_id: str) -> str:
        for row in self.record_rows:
            if row.id == scenario_id and row.valid:
                return row.status
        return "NOT_RUN"

    def relpath(self) -> str:
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return self.path.name


ActivePlan = Plan


def locate_active_plan(cwd: Optional[str]) -> Optional[Tuple[Path, Path]]:
    """Walk up from cwd to the first directory holding plan/ACTIVE (stop at a .git root).

    Returns ``(root, plan_path)`` or None. Same walk as the original hook.
    """
    if not cwd:
        return None
    for directory in [Path(cwd), *Path(cwd).parents]:
        marker = directory / "plan" / "ACTIVE"
        if marker.is_file():
            slug = marker.read_text(encoding="utf-8").strip()
            plan = directory / "plan" / f"{slug}.md"
            return (directory, plan) if slug and plan.is_file() else None
        if (directory / ".git").exists():
            return None
    return None


def find_active_plan(cwd: Optional[str]) -> Optional[Plan]:
    located = locate_active_plan(cwd)
    if located is None:
        return None
    return parse_plan(*located)


def root_for_plan_path(path: Path) -> Path:
    """Repository root for a plan given by path: the parent of plan/, else the nearest .git."""
    path = Path(path)
    parent = path.parent
    if parent.name == "plan":
        return parent.parent
    for directory in [parent, *parent.parents]:
        if (directory / ".git").exists():
            return directory
    return parent


def parse_plan(root: Path, path: Path) -> Plan:
    return parse_bytes(Path(root), Path(path), Path(path).read_bytes())


def parse_bytes(root: Path, path: Path, data: bytes) -> Plan:
    decoded = data.decode("utf-8")
    newline = _dominant_newline(decoded)
    universal = decoded.replace("\r\n", "\n").replace("\r", "\n")
    bom = universal.startswith("\ufeff")
    text = universal[1:] if bom else universal
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    values, where, fm_end, body_start = _front_matter(lines)
    tier = values.get("tier")
    plan = Plan(root=root, path=path, status="unknown", tier=tier)
    plan.lines = lines
    plan.front_matter = values
    plan.front_matter_lines = where
    plan.front_matter_end = fm_end
    plan.newline = newline
    plan.bom = bom
    plan.raw = data
    plan.team = values.get("team")
    plan.review = values.get("review")
    if values.get("state"):
        plan.state_path = root / values["state"]

    if plan.legacy:
        # Exactly the original hook: universal newlines, BOM kept, str.splitlines().
        plan.status, plan.open_tasks, plan.done_count = _legacy_counts(universal)
        plan.fenced = [False] * len(lines)
        plan.sections = _sections(lines, plan.fenced, body_start)
        plan.title = values.get("title") or _first_h1(lines, plan.fenced, body_start)
        return plan

    plan.status = _front_matter_status(lines, fm_end)
    plan.fenced = _fence_mask(lines, body_start)
    plan.sections = _sections(lines, plan.fenced, body_start)
    plan.title = values.get("title") or _first_h1(lines, plan.fenced, body_start)
    plan.open_tasks, plan.done_count = _tier_counts(lines, plan.fenced)
    _parse_requirements(plan)
    _parse_scenarios(plan)
    _parse_team(plan)
    _parse_tasks(plan)
    _parse_review(plan)
    _parse_workflow(plan)
    return plan


def _dominant_newline(decoded: str) -> str:
    crlf = decoded.count("\r\n")
    lone_cr = decoded.count("\r") - crlf
    lone_lf = decoded.count("\n") - crlf
    best = max((crlf, "\r\n"), (lone_lf, "\n"), (lone_cr, "\r"), key=lambda item: item[0])
    return best[1] if best[0] > 0 else "\n"


def _legacy_counts(universal: str) -> Tuple[str, List[str], int]:
    lines = universal.splitlines()
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
    return status, open_tasks, done


def _tier_counts(lines: List[str], fenced: List[bool]) -> Tuple[List[str], int]:
    """The legacy counting rules applied to the lines outside fenced blocks."""
    open_tasks: List[str] = []
    done = 0
    in_tasks = False
    for index, line in enumerate(lines):
        if fenced[index]:
            continue
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
    return open_tasks, done


def _front_matter(lines: List[str]) -> Tuple[Dict[str, str], Dict[str, int], int, int]:
    """Return (values, key line numbers, index of closing ---, index of first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, {}, 0, 0
    values: Dict[str, str] = {}
    where: Dict[str, int] = {}
    end = len(lines)
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
        match = FM_KEY.match(lines[index])
        if match:
            values[match.group(1)] = match.group(2)
            where[match.group(1)] = index + 1
    body_start = end + 1 if end < len(lines) else len(lines)
    return values, where, end, body_start


def _front_matter_status(lines: List[str], fm_end: int) -> str:
    status = "unknown"
    if lines and lines[0].strip() == "---":
        for line in lines[1:fm_end]:
            match = STATUS.match(line)
            if match:
                status = match.group(1)
    return status


def _fence_mask(lines: List[str], start: int) -> List[bool]:
    mask = [False] * len(lines)
    fence: Optional[str] = None
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is None:
            match = FENCE_OPEN.match(line)
            if match:
                fence = match.group(1)
                mask[index] = True
            continue
        mask[index] = True
        match = FENCE_CLOSE.match(line)
        if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            fence = None
    return mask


def _sections(lines: List[str], fenced: List[bool], start: int) -> List[Section]:
    heads: List[Tuple[int, str]] = []
    for index in range(start, len(lines)):
        if fenced[index]:
            continue
        match = H2.match(lines[index])
        if match:
            heads.append((index, match.group(1)))
    sections = []
    for position, (index, name) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        sections.append(Section(name=name, start=index, end=end))
    return sections


def _first_h1(lines: List[str], fenced: List[bool], start: int) -> str:
    for index in range(start, len(lines)):
        if not fenced[index] and lines[index].startswith("# "):
            return lines[index][2:].strip()
    return ""


def _body(plan: Plan, name: str):
    """Yield (index, line) for the unfenced lines of the first section with this name."""
    section = plan.section(name)
    if section is None:
        return
    for index in range(section.start + 1, section.end):
        if not plan.fenced[index]:
            yield index, plan.lines[index]


def _parse_requirements(plan: Plan) -> None:
    for index, line in _body(plan, "Acceptance criteria"):
        match = REQUIREMENT.match(line)
        if match:
            plan.requirements.append(
                Requirement(
                    id=match.group(2),
                    text=match.group(3).strip(),
                    done=match.group(1) in "xX",
                    line=index + 1,
                )
            )


def _scenario_refs(cell: str) -> List[str]:
    return SCENARIO_REF.findall(cell)


def _parse_scenarios(plan: Plan) -> None:
    section = plan.section("Scenarios")
    mode: Optional[str] = None  # None (coverage), "scenario", "record", "other"
    current: Optional[Scenario] = None
    last_field: Optional[str] = None

    def close_current(stop: int) -> None:
        if current is None:
            return
        current.end = _last_content(plan, current.line - 1, stop) + 1
        current.text = "\n".join(plan.lines[current.line - 1 : current.end])

    for index, line in _body(plan, "Scenarios"):
        if line.startswith("### "):
            close_current(index)
            current = None
            last_field = None
            head = SCENARIO_HEAD.match(line)
            if head:
                current = Scenario(id=head.group(1), title=head.group(2).strip(), line=index + 1, end=index + 1)
                plan.scenarios.append(current)
                mode = "scenario"
            elif line.rstrip() == RECORD_HEAD:
                mode = "record"
                if plan.record_line is None:
                    plan.record_line = index + 1
            else:
                mode = "other"
            continue
        if mode is None:
            match = COVERAGE_ROW.match(line)
            if match:
                plan.coverage.append(
                    CoverageRow(
                        requirement=match.group(1),
                        happy=_scenario_refs(match.group(2)),
                        other=_scenario_refs(match.group(3)),
                        not_applicable=match.group(4).strip(),
                        line=index + 1,
                    )
                )
        elif mode == "scenario" and current is not None:
            match = SCENARIO_FIELD.match(line)
            if match:
                name, value = match.group(1), match.group(2).strip()
                if name in current.fields:
                    last_field = None
                    continue
                current.fields[name] = value
                current.field_lines[name] = index + 1
                last_field = name
            elif line[:1] in (" ", "\t") and line.strip() and last_field:
                joined = current.fields[last_field]
                current.fields[last_field] = (joined + "\n" + line.strip()) if joined else line.strip()
            elif line.strip():
                last_field = None
        elif mode == "record" and plan.record_line is not None:
            candidate = CANDIDATE.match(line)
            if candidate and plan.candidate_line is None:
                plan.candidate = candidate.group(1).strip()
                plan.candidate_line = index + 1
                continue
            loose = RECORD_ROW_LOOSE.match(line)
            if loose:
                strict = RECORD_ROW.match(line)
                if strict:
                    plan.record_rows.append(
                        RecordRow(
                            id=strict.group(1),
                            status=strict.group(2),
                            valid=True,
                            evidence=strict.group(3).strip(),
                            blocker=strict.group(4).strip(),
                            line=index + 1,
                        )
                    )
                else:
                    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    plan.record_rows.append(
                        RecordRow(
                            id=loose.group(1),
                            status=cells[1] if len(cells) > 1 else "",
                            valid=False,
                            evidence="",
                            blocker="",
                            line=index + 1,
                        )
                    )
    if section is not None:
        close_current(section.end)

    for scenario in plan.scenarios:
        raw = scenario.fields.get("Requirement", "")
        tokens = [token.strip() for token in raw.split(",")] if raw.strip() else []
        scenario.requirements = [token for token in tokens if REQUIREMENT_ID.match(token)]
        scenario.requirements_valid = bool(tokens) and len(scenario.requirements) == len(tokens)
        owners = OWNERS.match(scenario.fields.get("Owners", "").strip())
        if owners:
            scenario.implementer = owners.group(1).strip().strip("`")
            scenario.executor = owners.group(2).strip().strip("`")


def _parse_team(plan: Plan) -> None:
    for index, line in _body(plan, "Team"):
        match = ROLE_ROW.match(line)
        if match:
            plan.team_roles.append(
                Role(
                    name=match.group(1),
                    kind=match.group(2),
                    host=match.group(3).strip(),
                    notes=match.group(4).strip(),
                    line=index + 1,
                )
            )
        elif ROLE_ROW_LOOSE.match(line):
            kinds = ", ".join(ROLE_KINDS)
            plan.role_issues.append((index + 1, f"role row must be `| role | Kind | Host agent | Notes |` with Kind one of {kinds}"))


def _parse_tasks(plan: Plan) -> None:
    heading = WAVE_HEAD if plan.tier in TEAM_TIERS else PHASE_HEAD
    wave: Optional[Wave] = None
    node: Optional[Node] = None
    seen_field_keys: Dict[str, int] = {}

    for index, line in _body(plan, "Tasks"):
        head = NODE_HEAD.match(line)
        ends_node = line.startswith("### ") or bool(head) or bool(line.strip() and not line[:1].isspace())
        if node is not None and ends_node:
            node.end = _last_content(plan, node.line - 1, index) + 1
            node = None
        if line.startswith("### "):
            match = heading.match(line)
            wave = Wave(index=int(match.group(1)), name=match.group(2) or None, line=index + 1) if match else None
            if wave is not None:
                plan.waves.append(wave)
            continue
        if head:
            mark = head.group(1)
            node = Node(
                id=head.group(2),
                title="",
                mark="x" if mark in "xX" else mark,
                line=index + 1,
                end=index + 1,
                wave=wave.index if wave is not None else None,
            )
            seen_field_keys = {}
            _parse_head_fields(node, head.group(3), index + 1, seen_field_keys)
            plan.nodes.append(node)
            if wave is not None:
                wave.nodes.append(node.id)
            continue
        if CHECKBOX_COL0.match(line):
            plan.task_issues.append(("E-TASK-ID", index + 1, "checkbox line has no node ID (expected `- [ ] ID title`)"))
            continue
        if CHECKBOX_INDENTED.match(line):
            plan.task_issues.append(("E-TASK-INDENT", index + 1, "indented checkbox line in ## Tasks"))
            continue
        if node is not None:
            match = NODE_FIELD.match(line)
            if match:
                _add_field(node, match.group(1), match.group(2).strip(), index + 1, seen_field_keys)
    if node is not None:
        section = plan.section("Tasks")
        stop = section.end if section is not None else len(plan.lines)
        node.end = _last_content(plan, node.line - 1, stop) + 1

    for node in plan.nodes:
        _interpret_fields(node)
    ids = [scenario.id for scenario in plan.scenarios]
    for node in plan.nodes:
        if node.scenarios_all:
            node.scenarios = list(dict.fromkeys(ids))


def _last_content(plan: Plan, start: int, stop: int) -> int:
    """Index of the last non-blank line in [start, stop)."""
    last = start
    for index in range(start, min(stop, len(plan.lines))):
        if plan.lines[index].strip():
            last = index
    return last


@dataclass
class HeadSegment:
    key: Optional[str]  # None for the title, else the inline field key as written
    parts: List[str]  # " — " separated pieces; a field's first piece reads "key: value"


def head_segments(rest: str) -> List[HeadSegment]:
    """Split a node head after its ID into the title and its inline ` — key: value` fields.

    A piece that reads ``key: value`` for a node field key starts a field; any other piece
    continues the segment before it. Joining every piece with " — " gives ``rest`` back.
    """
    pieces = rest.split(" — ")
    segments = [HeadSegment(None, [pieces[0]])]
    for piece in pieces[1:]:
        match = INLINE_FIELD.match(piece.strip())
        if match:
            segments.append(HeadSegment(match.group(1), [piece]))
        else:
            segments[-1].parts.append(piece)
    return segments


def _parse_head_fields(node: Node, rest: str, line: int, seen: Dict[str, int]) -> None:
    segments = head_segments(rest)
    title_parts = list(segments[0].parts)
    for segment in segments[1:]:
        match = INLINE_FIELD.match(segment.parts[0].strip())
        key = _add_field(node, match.group(1), match.group(2).strip(), line, seen)
        for piece in segment.parts[1:]:
            if key is None:
                title_parts.append(piece)
            else:
                node.fields[key] = node.fields[key] + " — " + piece
    node.title = " — ".join(title_parts).strip()


def _add_field(node: Node, key: str, value: str, line: int, seen: Dict[str, int]) -> Optional[str]:
    canonical = FIELD_ALIASES.get(key, key)
    if canonical in REPEATABLE_FIELDS:
        node.evidence.append(value)
        node.fields.setdefault(canonical, value)
        node.field_lines.setdefault(canonical, line)
        return canonical
    if canonical in seen:
        node.issues.append((line, f"node {node.id} repeats field '{canonical}' (first on line {seen[canonical]})"))
        return None
    seen[canonical] = line
    node.fields[canonical] = value
    node.field_lines[canonical] = line
    return canonical


def parse_path_list(value: str) -> Optional[List[str]]:
    """`a`, `b` -> ["a", "b"]; "—" -> []; None when the value breaks the grammar."""
    value = value.strip()
    if value in NONE_MARKERS:
        return []
    if not BACKTICK_LIST.match(value):
        return None
    return [item.strip() for item in BACKTICK_ITEM.findall(value)]


def _interpret_fields(node: Node) -> None:
    def bad(key: str, expected: str) -> None:
        node.issues.append((node.field_lines.get(key, node.line), f"node {node.id} field '{key}' must be {expected}"))

    if "owner" in node.fields:
        owner = node.fields["owner"].strip().strip("`")
        if ROLE_NAME.match(owner):
            node.owner = owner
        else:
            bad("owner", "a role name from ## Team")
    if "after" in node.fields:
        value = node.fields["after"].strip()
        if value in NONE_MARKERS or value == "none":
            node.after = []
        else:
            items = [item.strip() for item in value.split(",")]
            if value and all(NODE_ID.match(item) for item in items):
                node.after = items
            else:
                bad("after", "—, none, or a comma list of node IDs")
    for key in ("writes", "consumes", "produces"):
        if key in node.fields:
            items = parse_path_list(node.fields[key])
            if items is None:
                bad(key, "— or a comma list of `backticked` path patterns")
            else:
                setattr(node, key, items)
    if "scenarios" in node.fields:
        value = node.fields["scenarios"].strip()
        if value in NONE_MARKERS:
            node.scenarios = []
        elif value == "all":
            node.scenarios_all = True
            node.scenarios = []
        else:
            items = [item.strip() for item in value.split(",")]
            if value and all(SCENARIO_ID.match(item) for item in items):
                node.scenarios = list(dict.fromkeys(items))
            else:
                bad("scenarios", "—, all, or a comma list of scenario IDs")
    if "gate" in node.fields:
        value = node.fields["gate"].strip()
        if value in ("test", "review"):
            node.gate = value
        else:
            bad("gate", "test or review")


def _parse_review(plan: Plan) -> None:
    current: Optional[ReviewRound] = None
    for index, line in _body(plan, "Plan review"):
        match = ROUND.match(line)
        if match:
            current = ReviewRound(
                number=int(match.group(1)),
                reviewer=match.group(2),
                mode=match.group(3),
                digest=match.group(4),
                verdict=match.group(5),
                line=index + 1,
            )
            plan.review_rounds.append(current)
            continue
        waiver = WAIVER.match(line)
        if waiver:
            plan.waivers.append(Waiver(date=waiver.group(1), reason=waiver.group(2).strip(), line=index + 1))
            current = None
            continue
        finding = REVIEW_FINDING.match(line)
        if finding and current is not None:
            current.findings.append(
                ReviewFinding(
                    id=finding.group(1),
                    code=finding.group(2),
                    text=finding.group(3),
                    status=finding.group(4),
                    rest=finding.group(5).strip(),
                    line=index + 1,
                )
            )
            continue
        if line.strip() and not line[:1].isspace():
            current = None


def _parse_workflow(plan: Plan) -> None:
    for _index, line in _body(plan, "Workflow"):
        match = POLICY.match(line)
        if match:
            plan.policy.setdefault(match.group(1), int(match.group(2)))
