"""Check codes: each one fires on a minimal breakage and stays quiet on the valid fixtures."""

from __future__ import annotations

import re
import unittest
from typing import Callable, List, Tuple

from plan_loop_support import FIXTURES, TempRepo, codes, fixture_text, replace_once

from planlib import checks

Mutation = Callable[[str], str]


def sub(old: str, new: str) -> Mutation:
    return lambda text: replace_once(text, old, new)


def chain(*steps: Mutation) -> Mutation:
    def run(text: str) -> str:
        for step in steps:
            text = step(text)
        return text

    return run


def drop_wave_4(text: str) -> str:
    return re.sub(r"### Wave 4: review\n.*?\n\n## Verification", "## Verification", text, count=1, flags=re.S)


# (code, fixture, mutation, phase)
FIRES: List[Tuple[str, str, Mutation, str]] = [
    ("W-FM-SLUG", "base-ok", sub("slug: base-ok", "slug: greeting"), "draft"),
    ("E-FM-KEY", "base-ok", sub("status: planning", "status: drafting"), "draft"),
    ("E-FM-KEY", "base-ok", sub("review: pending", "review: maybe"), "draft"),
    ("E-FM-KEY", "base-ok", sub("tier: base", "tier: mega"), "draft"),
    ("E-FM-KEY", "base-ok", sub("review: pending\n", "review: pending\nstate: plan/sample.state.json\n"), "draft"),
    ("E-FM-KEY", "team-ok", sub("team: generic\n", ""), "draft"),
    ("E-FM-KEY", "team-ok", sub("team: generic", "team: Generic"), "draft"),
    ("E-FM-KEY", "workflow-ok", sub("state: plan/workflow-ok.state.json\n", ""), "draft"),
    ("E-FM-KEY", "workflow-ok", sub("state: plan/workflow-ok.state.json", "state: plan/other.state.json"), "draft"),
    ("E-SECTION", "base-ok", sub("## Verification\n", "### Verification\n"), "draft"),
    ("E-SECTION", "base-ok", sub("## Won't\n", "## Goal\nagain\n\n## Won't\n"), "draft"),
    ("E-SECTION", "workflow-ok", sub("## Workflow\n", "### Workflow\n"), "draft"),
    ("E-REQ-NONE", "base-ok", chain(sub("- [ ] A1 ", "- A1 "), sub("- [ ] A2 ", "- A2 ")), "draft"),
    ("E-REQ-DUP", "base-ok", sub("- [ ] A2 `greet` with", "- [ ] A1 `greet` with"), "draft"),
    ("E-SCEN-NONE", "base-ok", lambda t: t.replace("### AT-", "#### AT-"), "draft"),
    ("E-SCEN-DUP", "base-ok", sub("### AT-03 — name", "### AT-02 — name"), "draft"),
    ("E-SCEN-FIELD", "base-scen-field", lambda t: t, "draft"),
    ("E-SCEN-FIELD", "base-ok", sub("- Verification: run the command in a shell", "- Verification:"), "draft"),
    ("E-SCEN-FIELD", "base-ok", sub("- Actions: `./greet Ada`", "- Actions: <ordered steps>"), "draft"),
    ("E-SCEN-FIELD", "base-ok", sub("- Owners: implementer main; executor tester", "- Owners: main and tester"), "draft"),
    ("E-SCEN-FIELD", "base-ok", sub("- Owners: implementer main; executor tester", "- Owners: implementer main; executor <tester>"), "draft"),
    ("E-SCEN-FIELD", "base-ok", sub("- Requirement: A2", "- Requirement: A2 and more"), "draft"),
    ("E-SCEN-REQ", "base-ok", sub("- Requirement: A2", "- Requirement: A2, A9"), "draft"),
    ("E-COVERAGE-HAPPY", "base-no-happy", lambda t: t, "draft"),
    ("E-COVERAGE-HAPPY", "base-ok", sub("| A2 | AT-02 | — | persistence: nothing is stored |\n", ""), "draft"),
    ("E-COVERAGE-MAP", "base-ok", sub("| A1 | AT-01 | AT-03 |", "| A1 | AT-01 | AT-09 |"), "draft"),
    ("E-COVERAGE-MAP", "base-ok", sub("| A2 | AT-02 | — |", "| A2 | AT-02 | AT-03 |"), "draft"),
    ("E-COVERAGE-MAP", "base-ok", sub("- Requirement: A2", "- Requirement: A2, A1"), "draft"),
    ("E-RECORD", "base-ok", sub("### Execution record", "### Run log"), "draft"),
    ("E-RECORD", "base-ok", sub("| AT-03 | NOT_RUN | — | — |\n", ""), "draft"),
    ("E-RECORD", "base-ok", sub("| AT-03 | NOT_RUN | — | — |\n", "| AT-03 | NOT_RUN | — | — |\n| AT-03 | NOT_RUN | — | — |\n"), "draft"),
    ("E-RECORD", "base-ok", sub("| AT-03 | NOT_RUN | — | — |", "| AT-03 | DONE | — | — |"), "run"),
    ("E-RECORD", "base-ok", sub("| AT-03 | NOT_RUN | — | — |", "| AT-03 | PASS | ok | — |"), "draft"),
    ("E-RECORD", "base-ok", sub("| AT-03 | NOT_RUN | — | — |", "| AT-03 | PASS | ok | — |"), "approve"),
    ("E-TASK-NONE", "base-ok", lambda t: t.replace("- [ ] T", "* T"), "draft"),
    ("E-TASK-ID", "base-ok", sub("- [ ] T2 Document", "- [ ] Document"), "draft"),
    ("E-TASK-ID", "base-ok", sub("- [ ] T2 Document", "- [ ] T1 Document"), "draft"),
    ("E-TASK-ID", "base-ok", sub("- [ ] T2 Document", "- [ ] A2 Document"), "draft"),
    ("E-TASK-INDENT", "base-ok", sub("  - check: AT-01 by hand\n", "  - check: AT-01 by hand\n  - [ ] T2a sub step\n"), "draft"),
    ("W-TASK-VAGUE", "base-ok", sub("T2 Document the greet command", "T2 Investigate the docs"), "approve"),
    ("E-NODE-FIELD", "team-no-owner", lambda t: t, "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - check: `pytest tests/csv`\n", "  - check: `pytest tests/csv`\n  - owner: implementer\n"), "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - after: N1, N2", "  - after: N1 and N2"), "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - writes: `src/api/import.py`, `tests/api/test_import.py`", "  - writes: src/api/import.py"), "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - scenarios: AT-02\n", "  - scenarios: AT-2\n"), "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - scenarios: AT-02\n", "  - scenarios: AT-07\n"), "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - gate: review", "  - gate: smoke"), "draft"),
    ("E-NODE-FIELD", "team-ok", sub("  - after: G1\n", ""), "draft"),
    ("E-NODE-FIELD", "base-ok", sub("  - files: `README.md`\n", "  - files: `README.md`\n  - writes: `docs/greet.md`\n"), "draft"),
    ("E-TEAM-ROLE", "team-bad-role", lambda t: t, "draft"),
    ("E-TEAM-ROLE", "team-ok", sub("| `implementer` | writer |", "| `implementer` | orchestrator |"), "draft"),
    ("E-TEAM-ROLE", "team-ok", sub("| `reviewer` | reviewer | — | read-only |", "| `tester` | reviewer | — | read-only |"), "draft"),
    ("E-TEAM-ROLE", "team-ok", sub("| `reviewer` | reviewer |", "| `reviewer` | auditor |"), "draft"),
    ("E-NODE-KIND", "team-ok", sub("  - owner: implementer\n  - after: N1, N2", "  - owner: tester\n  - after: N1, N2"), "draft"),
    ("W-NODE-NOSCEN", "team-ok", sub("  - scenarios: AT-01\n", "  - scenarios: —\n"), "draft"),
    ("E-SCEN-UNCLAIMED", "team-unclaimed", lambda t: t, "draft"),
    ("E-SCEN-EXECUTOR", "team-ok", sub("executor tester", "executor reviewer"), "draft"),
    ("E-SCEN-EXECUTOR", "team-ok", sub("executor tester", "executor nobody"), "draft"),
    ("E-SCOPE-PATTERN", "team-ok", sub("`src/api/import.py`, `tests", "`src/**/import.py`, `tests"), "draft"),
    ("E-SCOPE-PATTERN", "team-ok", sub("`src/api/import.py`, `tests", "`/abs/import.py`, `tests"), "draft"),
    ("E-SCOPE-PATTERN", "team-ok", sub("`src/api/import.py`, `tests", "`../import.py`, `tests"), "draft"),
    ("E-SCOPE-PATTERN", "team-ok", sub("`src/api/import.py`, `tests", "`src/{a,b}.py`, `tests"), "draft"),
    ("E-SCOPE-PATTERN", "team-ok", sub("`src/api/import.py`, `tests", "`src/*/import.py`, `tests"), "draft"),
    ("E-SCOPE-OVERLAP", "team-overlap", lambda t: t, "draft"),
    ("E-SCOPE-OWNER", "team-ok", chain(
        sub("  - owner: implementer\n  - after: N1, N2", "  - owner: main\n  - after: N1, N2"),
        sub("`src/api/import.py`, `tests", "`src/csv/extra.py`, `tests"),
    ), "draft"),
    ("E-SCOPE-PLAN", "team-ok", sub("`src/api/import.py`, `tests", "`plan/notes.md`, `tests"), "draft"),
    ("E-DAG-UNKNOWN", "team-unknown-dep", lambda t: t, "draft"),
    ("E-DAG-UNKNOWN", "team-ok", sub("  - after: N1, N2", "  - after: N3"), "draft"),
    ("E-DAG-CYCLE", "team-cycle", lambda t: t, "draft"),
    ("E-WAVE-MISSING", "team-ok", sub("### Wave 1: parser and endpoint", "### Parsers"), "draft"),
    ("E-WAVE-MISSING", "team-ok", sub("### Wave 4: review", "### Wave 5: review"), "draft"),
    ("E-WAVE-MISSING", "team-ok", sub("\n## Verification", "\n### Wave 5: nothing\n\n## Verification"), "draft"),
    ("E-WAVE-ORDER", "team-wave-order", lambda t: t, "draft"),
    ("E-GATE-OWNER", "team-gate-owner", lambda t: t, "draft"),
    ("E-GATE-OWNER", "team-ok", sub("  - owner: reviewer\n  - after: G1", "  - owner: tester\n  - after: G1"), "draft"),
    ("E-GATE-WRITES", "team-ok", sub("  - after: G1\n  - writes: —", "  - after: G1\n  - writes: `docs/review.md`"), "draft"),
    ("E-GATE-WAVE", "team-gate-wave", lambda t: t, "draft"),
    ("E-GATE-FINAL-TEST", "team-ok", sub("  - scenarios: all", "  - scenarios: AT-01, AT-02"), "draft"),
    ("E-GATE-FINAL-REVIEW", "team-ok", drop_wave_4, "draft"),
    ("E-BRIEF-FIELD", "workflow-no-donewhen", lambda t: t, "draft"),
    ("E-BRIEF-FIELD", "workflow-ok", sub("  - check: `pytest tests/api`", "  - check: —"), "draft"),
    ("E-BRIEF-FIELD", "workflow-ok", sub("  - consumes: `src/csv/parser.py`\n", ""), "draft"),
    ("E-BRIEF-PRODUCES", "workflow-ok", sub("  - produces: `src/api/import.py`", "  - produces: `src/api/other.py`"), "draft"),
    ("E-BRIEF-CONSUMES", "workflow-ok", sub("  - consumes: `src/csv/parser.py`", "  - consumes: `src/missing.py`"), "draft"),
    ("E-REVIEW-MISSING", "base-no-review", lambda t: t, "approve"),
    ("E-REVIEW-VERDICT", "base-revise", lambda t: t, "approve"),
    ("E-REVIEW-OPEN", "base-revise", lambda t: t, "approve"),
    ("E-REVIEW-STALE", "base-ok", sub("## Goal\n", "## Goal\nextra line\n"), "approve"),
    ("W-REVIEW-NODIGEST", "base-ok", sub("digest: cef4820e8f30", "digest: unavailable"), "approve"),
    ("W-REVIEW-SELF", "base-ok", sub("mode: independent — digest: cef4820e8f30", "mode: self — digest: cef4820e8f30"), "approve"),
    ("E-REVIEW-STATE", "base-ok", lambda t: t, "run"),
    ("E-REVIEW-STATE", "base-ok", lambda t: t, "finish"),
    ("E-FINISH-OPEN", "base-ok", sub("review: pending", "review: passed"), "finish"),
    ("E-FINISH-SCEN", "base-ok", sub("review: pending", "review: passed"), "finish"),
    ("E-FINISH-OPEN", "legacy-running", lambda t: t, "finish"),
    ("W-LEGACY", "legacy-planning", lambda t: t, "draft"),
]

# (code, fixture, mutation, phase): the code must not appear.
QUIET: List[Tuple[str, str, Mutation, str]] = [
    ("E-RECORD", "base-ok", sub("| AT-03 | NOT_RUN | — | — |", "| AT-03 | PASS | ok | — |"), "run"),
    ("W-TASK-VAGUE", "base-ok", sub("T2 Document the greet command", "T2 Investigate the docs"), "run"),
    ("W-NODE-NOSCEN", "team-ok", sub("  - scenarios: AT-01\n", "  - scenarios: —\n"), "run"),
    ("E-SCOPE-PLAN", "team-ok", chain(
        sub("  - owner: implementer\n  - after: N1, N2", "  - owner: main\n  - after: N1, N2"),
        sub("`src/api/import.py`, `tests", "`plan/notes.md`, `tests"),
    ), "draft"),
    ("E-SCOPE-OWNER", "team-ok", sub("`src/api/import.py`, `tests", "`src/csv/extra.py`, `tests"), "draft"),
    ("E-REVIEW-STALE", "base-ok", sub("status: planning", "status: running"), "approve"),
    ("E-REVIEW-STALE", "base-ok", sub("  - F1 [B2] AT-02", "  - F1 [B2] the AT-02"), "approve"),
    ("E-REVIEW-STALE", "base-ok", sub("digest: cef4820e8f30", "digest: unavailable"), "approve"),
    ("E-REVIEW-MISSING", "base-waived", lambda t: t, "approve"),
    ("E-REVIEW-MISSING", "base-no-review", lambda t: t, "draft"),
    ("E-REVIEW-STATE", "base-ok", sub("review: pending", "review: waived"), "run"),
    ("E-REVIEW-OPEN", "base-revise", sub("— status: open", "— status: rejected (out of scope)"), "approve"),
    ("E-FINISH-OPEN", "base-ok", lambda t: t, "run"),
]


class CheckCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def findings(self, fixture: str, mutation: Mutation, phase: str):
        plan = self.repo.parse(fixture, mutation(fixture_text(fixture)))
        return checks.run_checks(plan, phase)

    def test_codes_fire(self) -> None:
        for code, fixture, mutation, phase in FIRES:
            with self.subTest(code=code, fixture=fixture, phase=phase):
                found = codes(self.findings(fixture, mutation, phase))
                self.assertIn(code, found)

    def test_codes_stay_quiet(self) -> None:
        for code, fixture, mutation, phase in QUIET:
            with self.subTest(code=code, fixture=fixture, phase=phase):
                found = codes(self.findings(fixture, mutation, phase))
                self.assertNotIn(code, found)

    def test_every_code_in_the_table_is_exercised(self) -> None:
        expected = {
            "W-LEGACY", "W-FM-SLUG", "E-FM-KEY", "E-SECTION", "E-REQ-NONE", "E-REQ-DUP", "E-SCEN-NONE",
            "E-SCEN-DUP", "E-SCEN-FIELD", "E-SCEN-REQ", "E-COVERAGE-HAPPY", "E-COVERAGE-MAP", "E-RECORD",
            "E-TASK-NONE", "E-TASK-ID", "E-TASK-INDENT", "W-TASK-VAGUE", "E-NODE-FIELD", "E-TEAM-ROLE",
            "E-NODE-KIND", "W-NODE-NOSCEN", "E-SCEN-UNCLAIMED", "E-SCEN-EXECUTOR", "E-SCOPE-PATTERN",
            "E-SCOPE-OVERLAP", "E-SCOPE-OWNER", "E-SCOPE-PLAN", "E-DAG-UNKNOWN", "E-DAG-CYCLE", "E-WAVE-MISSING",
            "E-WAVE-ORDER", "E-GATE-OWNER", "E-GATE-WRITES", "E-GATE-WAVE", "E-GATE-FINAL-TEST",
            "E-GATE-FINAL-REVIEW", "E-BRIEF-FIELD", "E-BRIEF-PRODUCES", "E-BRIEF-CONSUMES", "E-REVIEW-MISSING",
            "E-REVIEW-VERDICT", "E-REVIEW-STALE", "E-REVIEW-OPEN", "W-REVIEW-NODIGEST", "W-REVIEW-SELF",
            "E-REVIEW-STATE", "E-FINISH-OPEN", "E-FINISH-SCEN",
        }
        self.assertEqual({row[0] for row in FIRES}, expected)

    def test_consumes_may_name_an_existing_repository_path(self) -> None:
        text = replace_once(fixture_text("workflow-ok"), "  - consumes: `src/csv/parser.py`", "  - consumes: `docs/orders.md`")
        plan = self.repo.parse("workflow-ok", text)
        self.assertIn("E-BRIEF-CONSUMES", codes(checks.run_checks(plan, "draft")))
        (self.repo.root / "docs").mkdir()
        (self.repo.root / "docs" / "orders.md").write_text("x", encoding="utf-8")
        self.assertNotIn("E-BRIEF-CONSUMES", codes(checks.run_checks(plan, "draft")))

    def test_legacy_plan_gets_no_structure_checks(self) -> None:
        plan = self.repo.parse("legacy-running", fixture_text("legacy-running"))
        self.assertEqual(codes(checks.run_checks(plan, "draft")), {"W-LEGACY"})
        finish = checks.run_checks(plan, "finish")
        self.assertEqual(codes(finish), {"W-LEGACY", "E-FINISH-OPEN"})

    def test_finished_plan_passes_finish(self) -> None:
        text = fixture_text("base-ok").replace("- [ ] T", "- [x] T").replace("| NOT_RUN |", "| PASS |")
        text = replace_once(text, "review: pending", "review: passed")
        text = replace_once(text, "status: planning", "status: done")
        plan = self.repo.parse("base-ok", text)
        self.assertEqual(codes(checks.run_checks(plan, checks.infer_phase(plan.status))), set())

    def test_waiver_skips_review_checks(self) -> None:
        text = fixture_text("base-revise").replace(
            "## Changes", "- Waived by user: 2026-11-12 — accepted as is\n\n## Changes", 1
        )
        plan = self.repo.parse("base-revise", text)
        self.assertEqual(codes(checks.run_checks(plan, "approve")), set())


class FixtureCodesTest(unittest.TestCase):
    """The fixtures carry exactly the codes the acceptance scenarios expect."""

    EXPECTED = {
        "base-ok": (set(), set()),
        "base-no-happy": ({"E-COVERAGE-HAPPY"}, {"E-COVERAGE-HAPPY"}),
        "base-scen-field": ({"E-SCEN-FIELD"}, {"E-SCEN-FIELD"}),
        "base-no-review": (set(), {"E-REVIEW-MISSING"}),
        "base-revise": (set(), {"E-REVIEW-VERDICT", "E-REVIEW-OPEN"}),
        "base-waived": (set(), set()),
        "team-ok": (set(), set()),
        "team-cycle": ({"E-DAG-CYCLE", "E-WAVE-ORDER"}, {"E-DAG-CYCLE", "E-WAVE-ORDER"}),
        "team-unknown-dep": ({"E-DAG-UNKNOWN"}, {"E-DAG-UNKNOWN"}),
        "team-wave-order": ({"E-WAVE-ORDER"}, {"E-WAVE-ORDER"}),
        "team-no-owner": ({"E-NODE-FIELD"}, {"E-NODE-FIELD"}),
        "team-bad-role": ({"E-TEAM-ROLE"}, {"E-TEAM-ROLE"}),
        "team-gate-owner": ({"E-GATE-OWNER"}, {"E-GATE-OWNER"}),
        "team-overlap": ({"E-SCOPE-OVERLAP"}, {"E-SCOPE-OVERLAP"}),
        "team-gate-wave": ({"E-GATE-WAVE"}, {"E-GATE-WAVE"}),
        "team-unclaimed": ({"E-SCEN-UNCLAIMED"}, {"E-SCEN-UNCLAIMED"}),
        "workflow-ok": (set(), set()),
        "workflow-no-donewhen": ({"E-BRIEF-FIELD"}, {"E-BRIEF-FIELD"}),
        "legacy-planning": (set(), set()),
        "legacy-running": (set(), set()),
    }

    def test_twenty_fixtures(self) -> None:
        self.assertEqual({p.stem for p in FIXTURES.glob("*.md")}, set(self.EXPECTED))

    def test_error_codes_per_fixture(self) -> None:
        repo = TempRepo()
        self.addCleanup(repo.close)
        for name, (draft, approve) in self.EXPECTED.items():
            with self.subTest(fixture=name):
                plan = repo.parse(name, fixture_text(name))
                self.assertEqual(codes(checks.run_checks(plan, "draft"), "error"), draft)
                self.assertEqual(codes(checks.run_checks(plan, "approve"), "error"), approve)
                self.assertEqual(codes(checks.run_checks(plan, "draft"), "warning") - {"W-LEGACY"}, set())

    def test_tier_fixtures_share_the_contract_shape(self) -> None:
        for name in self.EXPECTED:
            if name.startswith("legacy-"):
                continue
            with self.subTest(fixture=name):
                text = fixture_text(name)
                self.assertIn("\nstatus: planning\n", text)
                self.assertIn("\nreview: pending\n", text)
                self.assertIn(f"\nslug: {name}\n", text)
                self.assertRegex(text, r"\n## Plan review\n(.*\n)*## Changes\n[^#]*$")


class PhaseTest(unittest.TestCase):
    def test_infer_phase(self) -> None:
        cases = {"planning": "draft", "approved": "run", "running": "run", "done": "finish", "abandoned": "draft", "unknown": "draft", None: "draft"}
        for status, phase in cases.items():
            with self.subTest(status=status):
                self.assertEqual(checks.infer_phase(status), phase)


class PatternTest(unittest.TestCase):
    def test_parse_pattern_forms(self) -> None:
        self.assertEqual(checks.parse_pattern("a/b.py").kind, "file")
        self.assertEqual(checks.parse_pattern("a/b/").kind, "tree")
        self.assertEqual(checks.parse_pattern("a/b/**").kind, "tree")
        self.assertEqual(checks.parse_pattern("a/*.py").kind, "glob")
        self.assertEqual(checks.parse_pattern("./README.md").segments, ("README.md",))
        for bad in ("/abs.py", "a/../b.py", "a/**/b.py", "**", "a/*/b.py", "a/{x,y}.py", "a/**.py", "", "a//b.py"):
            with self.subTest(pattern=bad):
                self.assertIsNone(checks.parse_pattern(bad))

    def test_overlap_rules(self) -> None:
        overlap = checks.raw_overlap
        self.assertTrue(overlap("src/", "src/a/**"))
        self.assertTrue(overlap("src/a/**", "src/a/b.py"))
        self.assertFalse(overlap("src/a/**", "src/ab/c.py"))
        self.assertTrue(overlap("src/a.py", "src/a.py"))
        self.assertFalse(overlap("src/a.py", "src/b.py"))
        self.assertTrue(overlap("src/*.py", "src/a.py"))
        self.assertFalse(overlap("src/*.py", "src/a.ts"))
        self.assertFalse(overlap("src/*.py", "lib/a.py"))
        self.assertFalse(overlap("src/*.py", "src/*.ts"))
        self.assertTrue(overlap("src/*.py", "src/*.py"))
        self.assertTrue(overlap("src/*.py", "src/test_*.py"))
        self.assertTrue(overlap("src/**", "src/x/*.py"))
        self.assertFalse(overlap("src/x/**", "src/*.py"))

    def test_contains(self) -> None:
        self.assertTrue(checks.raw_contains("src/**", "src/a/b.py"))
        self.assertTrue(checks.raw_contains("src/*.py", "src/a.py"))
        self.assertFalse(checks.raw_contains("src/a.py", "src/**"))
        self.assertFalse(checks.raw_contains("src/a.py", "src/b.py"))


if __name__ == "__main__":
    unittest.main()
