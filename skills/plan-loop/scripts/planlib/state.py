"""State document plan/<slug>.state.json: build, reconcile, validate, detect drift.

The plan markdown owns node definitions and completion marks; the state document adds
the execution record (attempts, times, running/claimed, executor, events). Only the CLI
writes it. ``sync`` rebuilds every derived field from the plan, keeps execution records
by node ID, lets the markdown win on completion marks (``reconciled`` events) and, after
approval, marks nodes whose definition changed, and their dependents, as stale.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import VERSION, checks
from .planfile import TEAM_TIERS, Node, Plan

SCHEMA_VERSION = 1
KIND = "plan-loop.state"
NODE_STATES = ("pending", "running", "claimed", "done", "blocked")
APPROVED_STATUSES = ("approved", "running", "done")
DIGEST_KEYS = (
    "id",
    "title",
    "owner",
    "after",
    "writes",
    "scenarios",
    "gate",
    "refs",
    "check",
    "consumes",
    "produces",
    "done-when",
    "wave",
)
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "plan-state.schema.json"
SCHEMA_KEYWORDS = {"type", "required", "properties", "additionalProperties", "items", "enum", "const", "pattern", "minimum"}
SCHEMA_ANNOTATIONS = {"$schema", "$id", "title", "description"}


class StateError(Exception):
    """The state document is unreadable or invalid."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class SchemaKeywordError(ValueError):
    """The schema uses a keyword this validator does not implement."""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def node_digest(node: Node) -> str:
    values = {
        "id": node.id,
        "title": node.title,
        "owner": node.owner,
        "after": list(node.after or []),
        "writes": list(node.writes or []),
        "scenarios": list(node.scenarios or []),
        "gate": node.gate,
        "refs": node.fields.get("refs"),
        "check": node.fields.get("check"),
        "consumes": list(node.consumes) if node.consumes is not None else None,
        "produces": list(node.produces) if node.produces is not None else None,
        "done-when": node.fields.get("done-when"),
        "wave": node.wave,
    }
    return sha256_hex(canonical({key: values[key] for key in DIGEST_KEYS}))


def definition_digest(digests: List[str]) -> str:
    """sha256 of the canonical JSON list of node digests in file order."""
    return sha256_hex(canonical(digests))


# --------------------------------------------------------------------------- location


@dataclass
class Location:
    declared: bool
    relpath: Optional[str] = None  # plan/<slug>.state.json
    path: Optional[Path] = None
    problem: Optional[str] = None  # set when the declared value is not plan/<slug>.state.json

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.is_file()

    @property
    def occupied(self) -> bool:
        """Something that is not a regular file (a directory, a socket) sits at the path."""
        return self.path is not None and self.path.exists() and not self.path.is_file()


def locate(plan: Plan) -> Location:
    declared = plan.tier in TEAM_TIERS and bool(plan.front_matter.get("state"))
    if not declared:
        return Location(False)
    expected = f"plan/{plan.slug}.state.json"
    if plan.front_matter["state"] != expected:
        return Location(True, expected, None, f"front matter state must be {expected}")
    return Location(True, expected, plan.root / "plan" / f"{plan.slug}.state.json")


# --------------------------------------------------------------------------- validation


_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def validate_schema(instance: Any, schema: dict, path: str = "$") -> List[str]:
    """Validate against the supported JSON Schema subset; unknown keywords raise."""
    unknown = set(schema) - SCHEMA_KEYWORDS - SCHEMA_ANNOTATIONS
    if unknown:
        raise SchemaKeywordError(f"{path}: unsupported schema keyword(s): {', '.join(sorted(unknown))}")
    errors: List[str] = []
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        for name in allowed:
            if name not in _TYPES:
                raise SchemaKeywordError(f"{path}: unsupported type {name!r}")
        if not any(_TYPES[name](instance) for name in allowed):
            return [f"{path}: expected {' or '.join(allowed)}"]
    if "const" in schema and not _same(instance, schema["const"]):
        errors.append(f"{path}: must be {json.dumps(schema['const'])}")
    if "enum" in schema and not any(_same(instance, option) for option in schema["enum"]):
        errors.append(f"{path}: must be one of {json.dumps(schema['enum'])}")
    if "pattern" in schema and isinstance(instance, str) and not re.search(schema["pattern"], instance):
        errors.append(f"{path}: does not match {schema['pattern']}")
    if "minimum" in schema and _TYPES["number"](instance) and instance < schema["minimum"]:
        errors.append(f"{path}: must be at least {schema['minimum']}")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing {key}")
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate_schema(value, properties[key], f"{path}.{key}"))
            elif extra is False:
                errors.append(f"{path}: unexpected key {key}")
            elif isinstance(extra, dict):
                errors.extend(validate_schema(value, extra, f"{path}.{key}"))
    if isinstance(instance, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(instance):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{index}]"))
    return errors


_SCHEMA_CACHE: Dict[str, dict] = {}


def load_schema() -> dict:
    key = str(SCHEMA_PATH)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[key]


def semantic_problems(doc: dict) -> List[str]:
    """Checks the schema cannot express: edge ends, wave cover, counts, event order."""
    problems: List[str] = []
    ids = [node["id"] for node in doc["nodes"]]
    known = set(ids)
    if len(known) != len(ids):
        problems.append("nodes: duplicate node id")
    for edge in doc["edges"]:
        for end in ("from", "to"):
            if edge[end] not in known:
                problems.append(f"edges: {edge['from']} -> {edge['to']} names unknown node {edge[end]}")
    placed: Dict[str, int] = {}
    for wave in doc["waves"]:
        for node_id in wave["nodes"]:
            placed[node_id] = placed.get(node_id, 0) + 1
            if node_id not in known:
                problems.append(f"waves: wave {wave['index']} names unknown node {node_id}")
    for node_id in ids:
        if placed.get(node_id, 0) != 1:
            problems.append(f"waves: node {node_id} appears in {placed.get(node_id, 0)} waves; it must appear in exactly 1")
    expected = {state: 0 for state in NODE_STATES}
    for node in doc["nodes"]:
        expected[node["state"]] += 1
    if doc["counts"] != expected:
        problems.append(f"counts: {json.dumps(doc['counts'], sort_keys=True)} does not match the node states {json.dumps(expected, sort_keys=True)}")
    previous = 0
    for event in doc["events"]:
        if event["seq"] <= previous:
            problems.append(f"events: seq {event['seq']} does not increase")
        previous = event["seq"]
    return problems


def validate(doc: Any) -> List[str]:
    try:
        problems = validate_schema(doc, load_schema())
    except SchemaKeywordError as exc:
        return [str(exc)]
    if problems:
        return problems
    return semantic_problems(doc)


def load(path: Path, plan: Optional[Plan] = None) -> dict:
    """Read and validate a state document; raises StateError."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StateError([f"cannot read {path.name}: {exc}"]) from None
    problems = validate(doc)
    if not problems and plan is not None and doc["plan"]["slug"] != plan.slug:
        problems.append(f"plan.slug is {doc['plan']['slug']}, the plan is {plan.slug}")
    if problems:
        raise StateError(problems)
    return doc


def encode(doc: dict) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write(path: Path, doc: dict) -> None:
    write_bytes(path, encode(doc))


def write_bytes(path: Path, data: bytes) -> None:
    """Write through a temporary file in the same directory and os.replace it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o7777)
        else:
            os.chmod(temporary, 0o644)
        os.replace(temporary, str(path))
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


# --------------------------------------------------------------------------- drift


@dataclass
class Inspection:
    location: Location
    drift: str  # none, stale, missing, invalid
    doc: Optional[dict] = None
    problems: List[str] = field(default_factory=list)

    def info(self) -> dict:
        return {
            "declared": self.location.declared,
            "path": self.location.relpath,
            "exists": self.location.exists,
            "drift": self.drift,
            "staleNodes": [node["id"] for node in self.doc["nodes"] if node["stale"]] if self.doc else [],
        }


def inspect(plan: Plan) -> Inspection:
    location = locate(plan)
    if not location.declared:
        return Inspection(location, "none")
    if location.problem:
        return Inspection(location, "invalid", problems=[location.problem])
    if location.occupied:
        return Inspection(location, "invalid", problems=["not a regular file"])
    if not location.exists:
        return Inspection(location, "missing")
    try:
        doc = load(location.path, plan)
    except StateError as exc:
        return Inspection(location, "invalid", problems=exc.problems)
    drift = "stale" if doc["plan"]["sha256"] != sha256_hex(plan.raw) else "none"
    return Inspection(location, drift, doc)


def findings(plan: Plan, inspection: Optional[Inspection] = None) -> List[checks.Finding]:
    """E-STATE-* findings for the run and finish phases."""
    inspection = inspection or inspect(plan)
    result: List[checks.Finding] = []
    if not inspection.location.declared:
        return result
    line = plan.front_matter_lines.get("state")
    relpath = inspection.location.relpath
    if inspection.drift == "missing":
        result.append(checks.Finding("E-STATE-MISSING", f"{relpath} does not exist; run sync", line))
    elif inspection.drift == "invalid":
        for problem in inspection.problems:
            result.append(checks.Finding("E-STATE-SCHEMA", f"{relpath}: {problem}", line))
    elif inspection.drift == "stale":
        result.append(checks.Finding("E-STATE-STALE", f"{relpath} was synced from a different plan file; run sync", line))
    if inspection.doc is not None:
        result.extend(stale_done_findings(plan, inspection.doc))
    return result


def stale_done_findings(plan: Plan, doc: dict) -> List[checks.Finding]:
    result = []
    for entry in doc["nodes"]:
        if entry["stale"] and entry["state"] == "done":
            node = plan.node(entry["id"])
            result.append(
                checks.Finding(
                    "E-STATE-NODE-STALE",
                    f"node {entry['id']} is done but its definition changed after approval; run node reset {entry['id']} --cascade",
                    node.line if node else None,
                    entry["id"],
                )
            )
    return result


def node_states(doc: dict) -> Dict[str, str]:
    return {node["id"]: node["state"] for node in doc["nodes"]}


def node_entry(doc: dict, node_id: str) -> dict:
    for node in doc["nodes"]:
        if node["id"] == node_id:
            return node
    raise KeyError(node_id)


def scenario_entry(doc: dict, scenario_id: str) -> dict:
    for scenario in doc["scenarios"]:
        if scenario["id"] == scenario_id:
            return scenario
    raise KeyError(scenario_id)


# --------------------------------------------------------------------------- sync


def add_event(
    doc: dict,
    kind: str,
    at: str,
    node: Optional[str] = None,
    scenario: Optional[str] = None,
    by: str = "",
    data: Optional[dict] = None,
) -> None:
    seq = doc["events"][-1]["seq"] + 1 if doc["events"] else 1
    doc["events"].append(
        {"seq": seq, "at": at, "type": kind, "node": node, "scenario": scenario, "by": by or "", "data": data or {}}
    )


def _fresh_node(state: str) -> dict:
    return {
        "stale": False,
        "state": state,
        "attempt": 0,
        "startedAt": None,
        "finishedAt": None,
        "executor": {"agent": None, "provider": None, "model": None, "effort": None},
        "confirmedBy": None,
        "lastError": None,
        "evidence": [],
    }


def _reconcile(mark_state: str, json_state: str) -> str:
    """The markdown wins on done, blocked and open."""
    if mark_state in ("done", "blocked"):
        return mark_state
    return "pending" if json_state in ("done", "blocked") else json_state


def dependents(plan: Plan, roots: List[str]) -> List[str]:
    """roots and every node that depends on them through after, in file order."""
    graph = checks.known_after(plan)
    found = set(roots)
    changed = True
    while changed:
        changed = False
        for node_id, deps in graph.items():
            if node_id not in found and found.intersection(deps):
                found.add(node_id)
                changed = True
    return [node.id for node in plan.nodes if node.id in found]


def candidate_of(plan: Plan) -> Optional[str]:
    value = (plan.candidate or "").strip()
    return None if value in ("", "—", "-") else value


@dataclass
class SyncResult:
    doc: dict
    created: bool
    reconciled: List[str]
    stale: List[str]


def sync(plan: Plan, previous: Optional[dict], at: str, by: str = "", explicit: bool = False) -> SyncResult:
    """Rebuild the state document from the plan, keeping execution records from previous."""
    created = previous is None
    doc = copy.deepcopy(previous) if previous is not None else None
    prev_nodes = {node["id"]: node for node in doc["nodes"]} if doc else {}
    prev_scenarios = {scenario["id"]: scenario for scenario in doc["scenarios"]} if doc else {}
    events = doc["events"] if doc else []
    revision = doc["plan"]["revision"] if doc else 1
    work = {"events": events}
    reconciled: List[str] = []

    digests: Dict[str, str] = {}
    changed: List[str] = []
    nodes = []
    for node in plan.nodes:
        digest = node_digest(node)
        digests[node.id] = digest
        prev = prev_nodes.get(node.id)
        if prev is None:
            entry = _fresh_node(node.mark_state)
        else:
            entry = {key: prev[key] for key in _fresh_node("pending")}
            target = _reconcile(node.mark_state, prev["state"])
            if target != prev["state"]:
                add_event(work, "reconciled", at, node=node.id, by=by, data={"from": prev["state"], "to": target})
                reconciled.append(node.id)
                entry["state"] = target
                if target == "done" and entry["finishedAt"] is None:
                    entry["finishedAt"] = at
            if prev["digest"] != digest:
                changed.append(node.id)
        role = plan.role(node.owner)
        nodes.append(
            {
                "id": node.id,
                "title": node.title,
                "kind": node.kind,
                "owner": node.owner,
                "ownerKind": role.kind if role is not None else None,
                "after": list(node.after or []),
                "writes": list(node.writes or []),
                "scenarios": list(node.scenarios or []),
                "wave": node.wave,
                "digest": digest,
                **entry,
            }
        )

    ids = [node.id for node in plan.nodes]
    added = [node_id for node_id in ids if node_id not in prev_nodes]
    removed = [node_id for node_id in prev_nodes if node_id not in ids]
    newly_stale: List[str] = []
    definition_changed = bool(not created and (changed or added or removed))
    if definition_changed and plan.status in APPROVED_STATUSES:
        revision += 1
        stale_ids = set(dependents(plan, changed)) if changed else set()
        for entry in nodes:
            if entry["id"] in stale_ids and not entry["stale"]:
                entry["stale"] = True
                newly_stale.append(entry["id"])

    rows = {}
    for row in plan.record_rows:
        if row.valid:
            rows.setdefault(row.id, row)
    scenarios = []
    for scenario in plan.scenarios:
        status = plan.scenario_status(scenario.id)
        row = rows.get(scenario.id)
        row_evidence = row.evidence if row is not None and row.evidence not in ("", "—", "-") else None
        prev = prev_scenarios.get(scenario.id)
        if prev is None:
            recorded = {
                "status": status,
                "candidate": candidate_of(plan) if status != "NOT_RUN" else None,
                "evidence": row_evidence if status != "NOT_RUN" else None,
                "recordedAt": None,
            }
        else:
            recorded = {key: prev[key] for key in ("status", "candidate", "evidence", "recordedAt")}
            if prev["status"] != status:
                add_event(work, "reconciled", at, scenario=scenario.id, by=by, data={"from": prev["status"], "to": status})
                reconciled.append(scenario.id)
                recorded = {"status": status, "candidate": candidate_of(plan), "evidence": row_evidence, "recordedAt": at}
        scenarios.append(
            {
                "id": scenario.id,
                "title": scenario.title,
                "requirements": list(scenario.requirements),
                "executor": scenario.executor,
                **recorded,
            }
        )

    states = {entry["id"]: entry["state"] for entry in nodes}
    counts = {state: 0 for state in NODE_STATES}
    for entry in nodes:
        counts[entry["state"]] += 1
    waves = []
    wave_states, _active = checks.wave_progress(plan, states)
    for position, wave in enumerate(plan.waves):
        waves.append({"index": wave.index, "name": wave.name or "", "nodes": list(wave.nodes), "state": wave_states[position]})

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "generator": {"name": "plan_loop.py", "version": VERSION},
        "updatedAt": at,
        "plan": {
            "slug": plan.slug,
            "path": f"plan/{plan.slug}.md",
            "title": plan.title,
            "tier": plan.tier,
            "team": plan.team,
            "status": plan.status,
            "review": plan.review,
            "sha256": sha256_hex(plan.raw),
            "definitionDigest": definition_digest([digests[node_id] for node_id in ids]),
            "revision": revision,
        },
        "requirements": [{"id": r.id, "text": r.text, "done": r.done} for r in plan.requirements],
        "scenarios": scenarios,
        "nodes": nodes,
        "edges": [{"from": dep, "to": node_id} for node_id, deps in checks.known_after(plan).items() for dep in deps],
        "waves": waves,
        "counts": counts,
        "events": events,
    }
    if explicit or created or definition_changed:
        add_event(
            result,
            "synced",
            at,
            by=by,
            data={
                "created": created,
                "revision": revision,
                "reconciled": list(reconciled),
                "stale": list(newly_stale),
                "added": added if not created else [],
                "removed": removed,
            },
        )
    return SyncResult(result, created, reconciled, newly_stale)
