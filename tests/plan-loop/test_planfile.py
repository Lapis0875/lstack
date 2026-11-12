"""Parser: plan discovery, legacy counting, tier grammar, fences, CRLF and BOM."""

from __future__ import annotations

import unittest
from pathlib import Path

import hook_reference
from plan_loop_support import FIXTURES, TempRepo, fixture_text, replace_once

from planlib import planfile

LEGACY_SAMPLES = {
    "indented and upper-case marks": (
        "---\nstatus: running\n---\n\n## Tasks\n- [ ] T1 one\n  - [ ] T1a nested\n- [X] T2 two\n"
        "    - [x] T3 deep done\n- [!] T4 blocked\n\n## Verification\n- [ ] not a task\n"
    ),
    "two task sections": "---\nstatus: running\n---\n## Tasks\n- [ ] A\n## Notes\n- [ ] B\n## Tasks\n- [x] C\n",
    "fenced lines still count": "---\nstatus: running\n---\n## Tasks\n```\n- [ ] in fence\n## Goal\n- [ ] after\n```\n",
    "no front matter": "## Tasks\n- [ ] A\n",
    "status outside front matter": "---\ntitle: x\n---\nstatus: running\n## Tasks\n- [ ] A\n",
    "unclosed front matter": "---\nstatus: running\n## Tasks\n- [ ] A\n",
    "crlf": "---\r\nstatus: planning\r\n---\r\n## Tasks\r\n- [ ] A\r\n- [x] B\r\n",
    "lone cr": "---\rstatus: planning\r---\r## Tasks\r- [ ] A\r",
    "bom": "\ufeff---\nstatus: running\n---\n## Tasks\n- [ ] A\n",
    "form feed splits": "---\nstatus: running\n---\n## Tasks\n- [ ] A\x0c- [ ] B\n",
}


class LegacyCountingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def assert_same_as_reference(self, slug: str, raw: bytes) -> planfile.Plan:
        plan = self.repo.parse(slug, "", raw=raw)
        expected = hook_reference.parse_plan(self.repo.root, self.repo.root / "plan" / f"{slug}.md")
        self.assertIsNone(plan.tier)
        self.assertEqual(plan.status, expected.status)
        self.assertEqual(plan.open_tasks, expected.open_tasks)
        self.assertEqual(plan.done_count, expected.done_count)
        return plan

    def test_legacy_fixtures_count_like_the_original_hook(self) -> None:
        for name in ("legacy-planning", "legacy-running"):
            with self.subTest(name=name):
                self.assert_same_as_reference(name, (FIXTURES / f"{name}.md").read_bytes())

    def test_legacy_running_fixture_counts(self) -> None:
        plan = self.assert_same_as_reference("legacy-running", (FIXTURES / "legacy-running.md").read_bytes())
        self.assertEqual(plan.status, "running")
        self.assertEqual(len(plan.open_tasks), 2)
        self.assertEqual(plan.done_count, 1)
        self.assertTrue(plan.open_tasks[0].startswith("T2 "))

    def test_edge_cases_count_like_the_original_hook(self) -> None:
        for label, text in LEGACY_SAMPLES.items():
            with self.subTest(case=label):
                self.assert_same_as_reference("sample", text.encode("utf-8"))

    def test_bom_legacy_status_matches_original_hook(self) -> None:
        plan = self.assert_same_as_reference("sample", LEGACY_SAMPLES["bom"].encode("utf-8"))
        self.assertEqual(plan.status, "unknown")


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_walks_up_to_plan_active(self) -> None:
        self.repo.write_plan("team-ok", fixture_text("team-ok"))
        nested = self.repo.root / "src" / "deep"
        nested.mkdir(parents=True)
        plan = planfile.find_active_plan(str(nested))
        self.assertIsNotNone(plan)
        self.assertEqual(plan.root, self.repo.root)
        self.assertEqual(plan.path, self.repo.root / "plan" / "team-ok.md")
        self.assertEqual(plan.tier, "team")

    def test_stops_at_git_root(self) -> None:
        self.repo.write_plan("team-ok", fixture_text("team-ok"))
        inner = self.repo.root / "inner"
        (inner / ".git").mkdir(parents=True)
        self.assertIsNone(planfile.find_active_plan(str(inner)))

    def test_missing_plan_file_or_empty_active(self) -> None:
        (self.repo.root / "plan" / "ACTIVE").write_text("nothing-here\n", encoding="utf-8")
        self.assertIsNone(planfile.find_active_plan(str(self.repo.root)))
        (self.repo.root / "plan" / "ACTIVE").write_text("\n", encoding="utf-8")
        self.assertIsNone(planfile.find_active_plan(str(self.repo.root)))
        self.assertIsNone(planfile.find_active_plan(""))
        self.assertIsNone(planfile.find_active_plan(None))

    def test_same_answer_as_original_discovery(self) -> None:
        self.repo.write_plan("legacy-running", fixture_text("legacy-running"))
        ours = planfile.find_active_plan(str(self.repo.root))
        theirs = hook_reference.find_active_plan(str(self.repo.root))
        self.assertEqual((ours.root, ours.path), (theirs.root, theirs.path))

    def test_root_for_plan_path(self) -> None:
        self.assertEqual(planfile.root_for_plan_path(self.repo.root / "plan" / "x.md"), self.repo.root)
        other = self.repo.root / "docs" / "plans"
        other.mkdir(parents=True)
        self.assertEqual(planfile.root_for_plan_path(other / "x.md"), self.repo.root)

    def test_active_plan_alias(self) -> None:
        self.assertIs(planfile.ActivePlan, planfile.Plan)
        plan = planfile.ActivePlan(root=Path("."), path=Path("plan/x.md"), status="planning", open_tasks=["T1"], done_count=0)
        self.assertEqual(plan.open_tasks, ["T1"])


class TierGrammarTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_team_fixture_structure(self) -> None:
        plan = self.repo.parse("team-ok", fixture_text("team-ok"))
        self.assertEqual((plan.status, plan.tier, plan.team, plan.review), ("planning", "team", "generic", "pending"))
        self.assertIsNone(plan.state_path)
        self.assertEqual([r.id for r in plan.requirements], ["A1", "A2"])
        self.assertEqual([s.id for s in plan.scenarios], ["AT-01", "AT-02"])
        self.assertEqual([(c.requirement, c.happy, c.other) for c in plan.coverage], [("A1", ["AT-01"], []), ("A2", ["AT-02"], [])])
        self.assertEqual([(r.name, r.kind) for r in plan.team_roles], [
            ("main", "orchestrator"), ("implementer", "writer"), ("tester", "executor"), ("reviewer", "reviewer"),
        ])
        self.assertEqual([n.id for n in plan.nodes], ["N1", "N2", "N3", "G1", "G2"])
        self.assertEqual([(w.index, w.nodes) for w in plan.waves], [(1, ["N1", "N2"]), (2, ["N3"]), (3, ["G1"]), (4, ["G2"])])
        n3 = plan.node("N3")
        self.assertEqual(n3.after, ["N1", "N2"])
        self.assertEqual(n3.writes, ["src/api/import.py", "tests/api/test_import.py"])
        self.assertEqual(n3.scenarios, ["AT-01", "AT-02"])
        self.assertEqual(n3.fields["check"], "`pytest tests/api`")
        g1 = plan.node("G1")
        self.assertEqual((g1.kind, g1.writes, g1.scenarios), ("gate-test", [], ["AT-01", "AT-02"]))
        self.assertTrue(g1.scenarios_all)
        self.assertEqual(plan.node("G2").kind, "gate-review")
        self.assertEqual(plan.scenario("AT-01").executor, "tester")
        self.assertEqual(plan.scenario("AT-02").requirements, ["A2"])
        self.assertEqual([(r.id, r.status) for r in plan.record_rows], [("AT-01", "NOT_RUN"), ("AT-02", "NOT_RUN")])
        self.assertEqual(plan.candidate, "—")
        self.assertEqual([(r.number, r.verdict, r.digest) for r in plan.review_rounds], [(1, "PASS", "e98147e968d8")])
        self.assertEqual((plan.open_tasks[0], plan.done_count, len(plan.open_tasks)), ("N1 CSV parser with header validation", 0, 5))

    def test_scenario_text_and_multiline_fields(self) -> None:
        text = replace_once(
            fixture_text("team-ok"),
            "- Actions: same request with `noheader.csv`\n",
            "- Actions: in order:\n  1) upload `noheader.csv`\n  2) count rows\n",
        )
        plan = self.repo.parse("sample", text)
        scenario = plan.scenario("AT-02")
        self.assertEqual(scenario.fields["Actions"], "in order:\n1) upload `noheader.csv`\n2) count rows")
        self.assertTrue(scenario.text.startswith("### AT-02 — headerless file rejected\n"))
        self.assertTrue(scenario.text.endswith("- Evidence required: response body, row count"))

    def test_workflow_fields_and_state(self) -> None:
        plan = self.repo.parse("workflow-ok", fixture_text("workflow-ok"))
        self.assertEqual(plan.tier, "workflow")
        self.assertEqual(plan.state_path, self.repo.root / "plan" / "workflow-ok.state.json")
        self.assertEqual(plan.policy, {"max-parallel": 4, "max-attempts": 2})
        n3 = plan.node("N3")
        self.assertEqual((n3.consumes, n3.produces), (["src/csv/parser.py"], ["src/api/import.py"]))
        self.assertIn("returns 201", n3.fields["done-when"])
        self.assertEqual(plan.node("N1").consumes, [])

    def test_base_inline_fields_alias_and_phases(self) -> None:
        plan = self.repo.parse("base-ok", fixture_text("base-ok"))
        t1, t2 = plan.node("T1"), plan.node("T2")
        self.assertEqual(t1.title, "Add the greet command")
        self.assertEqual(t1.writes, ["src/greet.py", "tests/test_greet.py"])
        self.assertEqual(t1.fields["check"], "`pytest tests/test_greet.py`")
        self.assertEqual(t2.writes, ["README.md"])
        self.assertEqual((t1.wave, t2.wave), (1, 1))
        self.assertEqual([r.verdict for r in plan.review_rounds], ["REVISE", "PASS"])
        self.assertEqual([(f.id, f.status) for f in plan.review_rounds[0].findings], [("F1", "fixed")])

    def test_title_keeps_dash_fragments_that_are_not_fields(self) -> None:
        text = replace_once(fixture_text("base-ok"), "- [ ] T2 Document the greet command\n", "- [ ] T2 Document greet — the short form\n")
        plan = self.repo.parse("sample", text)
        self.assertEqual(plan.node("T2").title, "Document greet — the short form")

    def test_marks(self) -> None:
        text = replace_once(fixture_text("team-ok"), "- [ ] N1 ", "- [x] N1 ")
        text = replace_once(text, "- [ ] N2 ", "- [!] N2 ")
        text = replace_once(text, "- [ ] G2 ", "- [X] G2 ")
        plan = self.repo.parse("sample", text)
        self.assertEqual([n.mark_state for n in plan.nodes], ["done", "blocked", "pending", "pending", "done"])
        self.assertEqual(plan.done_count, 2)

    def test_waiver(self) -> None:
        plan = self.repo.parse("base-waived", fixture_text("base-waived"))
        self.assertEqual([(w.date, w.reason) for w in plan.waivers], [("2026-11-12", "the user approved the plan without an independent review")])
        self.assertEqual(plan.review_rounds, [])


FENCED = """
## Contracts
```markdown
## Tasks
- [ ] Z9 not a node
### AT-99 — not a scenario
| A1 | AT-99 | — | — |
```
~~~~
## Goal
~~~
still fenced
~~~~
"""


class FenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_fenced_lines_are_ignored_in_tier_plans(self) -> None:
        text = replace_once(fixture_text("team-ok"), "\n## Scenarios\n", FENCED + "\n## Scenarios\n")
        plan = self.repo.parse("sample", text)
        self.assertEqual([s.name for s in plan.sections].count("Tasks"), 1)
        self.assertEqual([s.name for s in plan.sections].count("Goal"), 1)
        self.assertNotIn("Z9", [n.id for n in plan.nodes])
        self.assertNotIn("AT-99", [s.id for s in plan.scenarios])
        self.assertEqual(len(plan.coverage), 2)
        self.assertEqual(len(plan.open_tasks), 5)
        self.assertIn("```markdown", plan.section_body("Contracts"))

    def test_original_hook_would_count_the_fenced_checkbox(self) -> None:
        text = replace_once(fixture_text("team-ok"), "\n## Scenarios\n", FENCED + "\n## Scenarios\n")
        path = self.repo.write_plan("sample", text, active=False)
        self.assertEqual(len(hook_reference.parse_plan(self.repo.root, path).open_tasks), 6)

    def test_unclosed_fence_runs_to_end_of_file(self) -> None:
        text = replace_once(fixture_text("team-ok"), "## Tasks\n", "```\n## Tasks\n")
        plan = self.repo.parse("sample", text)
        self.assertIsNone(plan.section("Tasks"))
        self.assertEqual(plan.nodes, [])

    def test_shorter_or_other_fence_does_not_close(self) -> None:
        mask = planfile._fence_mask(["````", "```", "~~~~", "````  ", "after"], 0)
        self.assertEqual(mask, [True, True, True, True, False])


class LineEndingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def summary(self, plan: planfile.Plan):
        return (
            plan.status,
            plan.tier,
            [(n.id, n.line, n.end, n.after, n.writes) for n in plan.nodes],
            [(s.id, s.line, s.fields) for s in plan.scenarios],
            [(r.id, r.line) for r in plan.requirements],
            plan.lines,
        )

    def test_crlf_parses_like_lf(self) -> None:
        text = fixture_text("workflow-ok")
        lf = self.repo.parse("a", text)
        crlf = self.repo.parse("b", "", raw=text.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.summary(crlf), self.summary(lf))
        self.assertEqual((lf.newline, crlf.newline), ("\n", "\r\n"))

    def test_bom_is_dropped(self) -> None:
        text = fixture_text("base-ok")
        plain = self.repo.parse("a", text)
        bom = self.repo.parse("b", "", raw=b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertTrue(bom.bom)
        self.assertFalse(plain.bom)
        self.assertEqual(self.summary(bom), self.summary(plain))
        self.assertEqual(bom.status, "planning")

    def test_node_block_end(self) -> None:
        plan = self.repo.parse("team-ok", fixture_text("team-ok"))
        lines = plan.lines
        n2 = plan.node("N2")
        self.assertEqual(lines[n2.end - 1], "  - check: `pytest tests/orders/test_repo.py`")
        g2 = plan.node("G2")
        self.assertEqual(lines[g2.end - 1], "  - gate: review")


if __name__ == "__main__":
    unittest.main()
