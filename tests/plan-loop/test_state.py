"""State document: schema subset validator, sync and reconciliation, drift, stale nodes."""

from __future__ import annotations

import copy
import json
import unittest

from plan_loop_support import SCRIPTS, TempRepo, fixture_text, replace_once

from planlib import planfile, state

AT = "2026-11-12T10:00:00Z"


def running(text: str) -> str:
    text = replace_once(text, "status: planning", "status: running")
    return replace_once(text, "review: pending", "review: passed")


class ValidatorTest(unittest.TestCase):
    def test_keywords(self) -> None:
        schema = {
            "type": "object",
            "required": ["a", "b"],
            "additionalProperties": False,
            "properties": {
                "a": {"type": "integer", "minimum": 1},
                "b": {"type": "array", "items": {"enum": ["x", None]}},
                "c": {"const": 1},
                "d": {"type": ["string", "null"], "pattern": "^[a-z]+$"},
            },
        }
        self.assertEqual(state.validate_schema({"a": 1, "b": ["x", None], "c": 1, "d": None}, schema), [])
        problems = state.validate_schema({"a": 0, "b": ["y"], "c": True, "d": "A", "e": 1}, schema)
        self.assertEqual(len(problems), 5, problems)
        self.assertEqual(state.validate_schema({"b": []}, schema), ["$: missing a"])
        self.assertEqual(state.validate_schema(True, {"type": "integer"}), ["$: expected integer"])
        self.assertEqual(state.validate_schema(1.5, {"type": "number", "minimum": 2}), ["$: must be at least 2"])

    def test_unknown_keyword_fails(self) -> None:
        with self.assertRaises(state.SchemaKeywordError):
            state.validate_schema({}, {"type": "object", "minProperties": 1})
        with self.assertRaises(state.SchemaKeywordError):
            state.validate_schema({"a": 1}, {"type": "object", "properties": {"a": {"oneOf": []}}})
        with self.assertRaises(state.SchemaKeywordError):
            state.validate_schema("x", {"type": "text"})

    def test_schema_file_uses_only_the_subset(self) -> None:
        schema = json.loads((SCRIPTS.parent / "schemas" / "plan-state.schema.json").read_text(encoding="utf-8"))
        seen = set()

        def walk(node):
            if isinstance(node, dict):
                seen.update(node)
                for key, value in node.items():
                    if key == "properties":
                        for child in value.values():
                            walk(child)
                    elif key in ("items", "additionalProperties"):
                        walk(value)

        walk(schema)
        self.assertLessEqual(seen, state.SCHEMA_KEYWORDS | state.SCHEMA_ANNOTATIONS)


class SyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_create_from_workflow_plan(self) -> None:
        plan = self.repo.parse("workflow-ok", fixture_text("workflow-ok"))
        result = state.sync(plan, None, AT, explicit=True)
        doc = result.doc
        self.assertTrue(result.created)
        self.assertEqual(state.validate(doc), [])
        self.assertEqual((doc["schemaVersion"], doc["kind"], doc["generator"]["name"]), (1, "plan-loop.state", "plan_loop.py"))
        self.assertEqual(len(doc["nodes"]), 5)
        self.assertEqual(doc["edges"], [{"from": "N1", "to": "N3"}, {"from": "N2", "to": "N3"}, {"from": "N3", "to": "G1"}, {"from": "G1", "to": "G2"}])
        self.assertEqual([w["nodes"] for w in doc["waves"]], [["N1", "N2"], ["N3"], ["G1"], ["G2"]])
        self.assertEqual([w["state"] for w in doc["waves"]], ["active", "pending", "pending", "pending"])
        self.assertEqual(doc["counts"], {"pending": 5, "running": 0, "claimed": 0, "done": 0, "blocked": 0})
        self.assertEqual(doc["plan"]["path"], "plan/workflow-ok.md")
        self.assertEqual(doc["plan"]["sha256"], state.sha256_hex(plan.raw))
        self.assertEqual(doc["plan"]["revision"], 1)
        self.assertEqual([e["type"] for e in doc["events"]], ["synced"])
        g1 = doc["nodes"][3]
        self.assertEqual((g1["kind"], g1["owner"], g1["ownerKind"], g1["scenarios"]), ("gate-test", "tester", "executor", ["AT-01", "AT-02"]))
        self.assertEqual(doc["scenarios"][0]["status"], "NOT_RUN")

    def test_node_digest_covers_the_definition_fields(self) -> None:
        plan = self.repo.parse("workflow-ok", fixture_text("workflow-ok"))
        base = state.node_digest(plan.node("N3"))
        for old, new in (
            ("  - check: `pytest tests/api`", "  - check: `pytest -x tests/api`"),
            ("  - done-when: POST", "  - done-when: GET"),
            ("- [ ] N3 Import endpoint", "- [ ] N3 Import endpoint v2"),
            ("  - after: N1, N2", "  - after: N1"),
        ):
            with self.subTest(change=new):
                changed = self.repo.parse("workflow-ok", replace_once(fixture_text("workflow-ok"), old, new))
                self.assertNotEqual(state.node_digest(changed.node("N3")), base)
        marked = self.repo.parse("workflow-ok", replace_once(fixture_text("workflow-ok"), "- [ ] N3 ", "- [x] N3 "))
        self.assertEqual(state.node_digest(marked.node("N3")), base)

    def test_reconcile_md_wins(self) -> None:
        text = running(fixture_text("workflow-ok"))
        plan = self.repo.parse("workflow-ok", text)
        doc = state.sync(plan, None, AT).doc
        state.node_entry(doc, "N2")["state"] = "running"
        state.node_entry(doc, "N1")["state"] = "done"
        edited = replace_once(text, "- [ ] N2 ", "- [x] N2 ")
        result = state.sync(self.repo.parse("workflow-ok", edited), doc, AT, explicit=True)
        self.assertEqual(result.reconciled, ["N1", "N2"])
        self.assertEqual(state.node_states(result.doc)["N1"], "pending")
        self.assertEqual(state.node_states(result.doc)["N2"], "done")
        events = [(e["type"], e["node"], e["data"].get("to")) for e in result.doc["events"] if e["type"] == "reconciled"]
        self.assertEqual(events, [("reconciled", "N1", "pending"), ("reconciled", "N2", "done")])

    def test_running_and_claimed_survive_sync(self) -> None:
        plan = self.repo.parse("workflow-ok", running(fixture_text("workflow-ok")))
        doc = state.sync(plan, None, AT).doc
        state.node_entry(doc, "N1")["state"] = "claimed"
        state.node_entry(doc, "N1")["attempt"] = 1
        doc["counts"] = {"pending": 4, "running": 0, "claimed": 1, "done": 0, "blocked": 0}
        result = state.sync(plan, doc, AT)
        self.assertEqual(state.node_entry(result.doc, "N1")["state"], "claimed")
        self.assertEqual(state.node_entry(result.doc, "N1")["attempt"], 1)
        self.assertEqual(result.reconciled, [])

    def test_scenario_reconcile(self) -> None:
        text = running(fixture_text("workflow-ok"))
        doc = state.sync(self.repo.parse("workflow-ok", text), None, AT).doc
        edited = replace_once(text, "| AT-01 | NOT_RUN | — | — |", "| AT-01 | FAIL | 500 on upload | — |")
        result = state.sync(self.repo.parse("workflow-ok", edited), doc, AT)
        self.assertEqual(result.reconciled, ["AT-01"])
        self.assertEqual(state.scenario_entry(result.doc, "AT-01")["status"], "FAIL")
        self.assertEqual(state.scenario_entry(result.doc, "AT-01")["evidence"], "500 on upload")

    def test_definition_change_after_approval_marks_stale_downstream(self) -> None:
        text = running(fixture_text("workflow-ok"))
        doc = state.sync(self.repo.parse("workflow-ok", text), None, AT).doc
        edited = replace_once(text, "  - check: `pytest tests/csv`", "  - check: `pytest -x tests/csv`")
        result = state.sync(self.repo.parse("workflow-ok", edited), doc, AT)
        self.assertEqual(result.stale, ["N1", "N3", "G1", "G2"])
        self.assertEqual(result.doc["plan"]["revision"], 2)
        self.assertFalse(state.node_entry(result.doc, "N2")["stale"])
        self.assertNotEqual(result.doc["plan"]["definitionDigest"], doc["plan"]["definitionDigest"])

    def test_definition_change_before_approval_is_not_stale(self) -> None:
        text = fixture_text("workflow-ok")
        doc = state.sync(self.repo.parse("workflow-ok", text), None, AT).doc
        edited = replace_once(text, "  - check: `pytest tests/csv`", "  - check: `pytest -x tests/csv`")
        result = state.sync(self.repo.parse("workflow-ok", edited), doc, AT)
        self.assertEqual(result.stale, [])
        self.assertEqual(result.doc["plan"]["revision"], 1)

    def test_semantic_problems(self) -> None:
        doc = state.sync(self.repo.parse("workflow-ok", fixture_text("workflow-ok")), None, AT).doc
        cases = {
            "edge end": lambda d: d["edges"].append({"from": "N1", "to": "N9"}),
            "wave cover": lambda d: d["waves"][0]["nodes"].remove("N2"),
            "wave twice": lambda d: d["waves"][1]["nodes"].append("N1"),
            "counts": lambda d: d["counts"].update(pending=4),
            "seq": lambda d: d["events"].append(dict(d["events"][0])),
        }
        for label, breaker in cases.items():
            with self.subTest(case=label):
                broken = copy.deepcopy(doc)
                breaker(broken)
                self.assertNotEqual(state.validate(broken), [])
        missing = copy.deepcopy(doc)
        del missing["edges"]
        self.assertEqual(state.validate(missing), ["$: missing edges"])


class InspectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def plan(self, text: str):
        path = self.repo.write_plan("workflow-ok", text)
        return planfile.parse_plan(self.repo.root, path)

    def test_drift_values(self) -> None:
        text = running(fixture_text("workflow-ok"))
        plan = self.plan(text)
        self.assertEqual(state.inspect(plan).drift, "missing")
        self.assertEqual([f.code for f in state.findings(plan)], ["E-STATE-MISSING"])
        doc = state.sync(plan, None, AT).doc
        state.write(self.repo.root / "plan" / "workflow-ok.state.json", doc)
        self.assertEqual(state.inspect(plan).drift, "none")
        self.assertEqual(state.findings(plan), [])
        stale_plan = self.plan(replace_once(text, "- [ ] N2 ", "- [x] N2 "))
        self.assertEqual(state.inspect(stale_plan).drift, "stale")
        self.assertEqual([f.code for f in state.findings(stale_plan)], ["E-STATE-STALE"])
        (self.repo.root / "plan" / "workflow-ok.state.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(state.inspect(stale_plan).drift, "invalid")
        self.assertEqual({f.code for f in state.findings(stale_plan)}, {"E-STATE-SCHEMA"})

    def test_stale_done_node(self) -> None:
        text = running(fixture_text("workflow-ok"))
        plan = self.plan(text)
        doc = state.sync(plan, None, AT).doc
        entry = state.node_entry(doc, "N1")
        entry["state"], entry["stale"] = "done", True
        doc["counts"] = {"pending": 4, "running": 0, "claimed": 0, "done": 1, "blocked": 0}
        state.write(self.repo.root / "plan" / "workflow-ok.state.json", doc)
        findings = state.findings(plan)
        self.assertEqual([(f.code, f.node) for f in findings], [("E-STATE-NODE-STALE", "N1")])
        self.assertEqual(state.inspect(plan).info()["staleNodes"], ["N1"])

    def test_undeclared(self) -> None:
        plan = self.plan(fixture_text("team-ok").replace("slug: team-ok", "slug: workflow-ok"))
        inspection = state.inspect(plan)
        self.assertEqual(inspection.info(), {"declared": False, "path": None, "exists": False, "drift": "none", "staleNodes": []})

    def test_wrong_state_path(self) -> None:
        plan = self.plan(replace_once(fixture_text("workflow-ok"), "state: plan/workflow-ok.state.json", "state: ../x.json"))
        self.assertEqual(state.inspect(plan).drift, "invalid")

    def test_atomic_write_keeps_mode(self) -> None:
        target = self.repo.root / "plan" / "x.json"
        target.write_text("{}", encoding="utf-8")
        target.chmod(0o640)
        state.write(target, {"a": 1})
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual([p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
