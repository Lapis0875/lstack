"""Review digest, wave layout, status data and node briefs."""

from __future__ import annotations

import hashlib
import itertools
import unittest

from plan_loop_support import TempRepo, fixture_text, replace_once

from planlib import checks

RECORDED = {"base-ok": "cef4820e8f30", "team-ok": "e98147e968d8", "workflow-ok": "48a8aee49756", "base-revise": "95e43bc62715"}


class DigestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def digest(self, text: str, slug: str = "sample", raw: bytes = None) -> str:
        return checks.review_digest(self.repo.parse(slug, text, raw=raw))

    def test_known_value(self) -> None:
        text = "---\ntitle: t\nstatus: planning\nreview: pending\ntier: base\n---\nbody  \n\n## Plan review\n- Round 1\n\n## Changes\nx\t\n\n\n"
        expected = hashlib.sha256("---\ntitle: t\ntier: base\n---\nbody\n\n## Changes\nx\n".encode("utf-8")).hexdigest()
        self.assertEqual(self.digest(text), expected)

    def test_fixture_rounds_hold_the_current_digest(self) -> None:
        for name, short in RECORDED.items():
            with self.subTest(fixture=name):
                self.assertEqual(self.digest(fixture_text(name), name)[:12], short)

    def test_ignores_status_review_and_the_review_section(self) -> None:
        text = fixture_text("base-ok")
        base = self.digest(text)
        variants = [
            replace_once(text, "status: planning", "status: approved"),
            replace_once(text, "review: pending", "review: passed"),
            replace_once(text, "- Round 2 —", "- Round 2  —"),
            replace_once(text, "## Changes\n(none)\n", "## Changes\n(none)   \n\n\n"),
            replace_once(text, "## Goal\n", "## Goal   \n"),
        ]
        for variant in variants:
            with self.subTest(variant=variant[:0]):
                self.assertEqual(self.digest(variant), base)

    def test_changes_with_the_body(self) -> None:
        text = fixture_text("base-ok")
        base = self.digest(text)
        self.assertNotEqual(self.digest(replace_once(text, "## Goal\n", "## Goal\nextra line\n")), base)
        self.assertNotEqual(self.digest(replace_once(text, "title: Greeting command", "title: Greetings")), base)
        self.assertNotEqual(self.digest(replace_once(text, "## Won't\n", "status: draft\n\n## Won't\n")), base)

    def test_line_ends_and_bom_do_not_matter(self) -> None:
        text = fixture_text("team-ok")
        base = self.digest(text)
        self.assertEqual(self.digest("", raw=text.replace("\n", "\r\n").encode("utf-8")), base)
        self.assertEqual(self.digest("", raw=b"\xef\xbb\xbf" + text.encode("utf-8")), base)

    def test_fenced_review_heading_is_content(self) -> None:
        def variant(word: str) -> str:
            block = f"```\n## Plan review\n{word}\n```\n\n## Verification\n"
            return replace_once(fixture_text("team-ok"), "## Verification\n", block)

        self.assertNotEqual(self.digest(variant("alpha")), self.digest(variant("beta")))


class WavesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_team_ok_matches_declared(self) -> None:
        plan = self.repo.parse("team-ok", fixture_text("team-ok"))
        proposed = checks.propose_waves(plan)
        self.assertEqual(proposed, [["N1", "N2"], ["N3"], ["G1"], ["G2"]])
        self.assertEqual(proposed, checks.declared_waves(plan))

    def test_overlap_moves_the_later_node_and_its_dependents(self) -> None:
        plan = self.repo.parse("team-overlap", fixture_text("team-overlap"))
        self.assertEqual(checks.propose_waves(plan), [["N1"], ["N2"], ["N3"], ["G1"], ["G2"]])

    def test_gate_leaves_a_work_wave(self) -> None:
        plan = self.repo.parse("team-gate-wave", fixture_text("team-gate-wave"))
        self.assertEqual(checks.propose_waves(plan), [["N1", "N2"], ["N3"], ["G3", "G1"], ["G2"]])

    def test_dependency_levels_ignore_declared_waves(self) -> None:
        plan = self.repo.parse("team-wave-order", fixture_text("team-wave-order"))
        self.assertEqual(checks.propose_waves(plan), [["N1"], ["N2"], ["N3"], ["G1"], ["G2"]])

    def test_cycle_has_no_layout(self) -> None:
        plan = self.repo.parse("team-cycle", fixture_text("team-cycle"))
        self.assertIsNone(checks.propose_waves(plan))
        self.assertEqual(checks.find_cycles(plan), [["N1", "N3"]])


class StatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_team_ok_status(self) -> None:
        data = checks.build_status(self.repo.parse("team-ok", fixture_text("team-ok")))
        self.assertEqual(data["phase"], "draft")
        self.assertEqual([(n["id"], n["owner"], n["ownerKind"]) for n in data["nodes"]], [
            ("N1", "implementer", "writer"), ("N2", "implementer", "writer"), ("N3", "implementer", "writer"),
            ("G1", "tester", "executor"), ("G2", "reviewer", "reviewer"),
        ])
        self.assertEqual(data["ready"], ["N1", "N2"])
        self.assertEqual(data["counts"], {"pending": 5, "running": 0, "claimed": 0, "done": 0, "blocked": 0})
        self.assertEqual(data["activeWave"], 1)
        self.assertEqual([w["state"] for w in data["waves"]], ["active", "pending", "pending", "pending"])
        self.assertEqual([(s["id"], s["status"], s["claimedBy"]) for s in data["scenarios"]], [
            ("AT-01", "NOT_RUN", ["N2", "N3"]), ("AT-02", "NOT_RUN", ["N1", "N3"]),
        ])
        self.assertEqual(data["state"], {"declared": False, "path": None, "exists": False, "drift": "none", "staleNodes": []})
        self.assertIsNone(data["legacy"])
        g1 = data["nodes"][3]
        self.assertEqual((g1["kind"], g1["scenarios"], g1["writes"], g1["wave"]), ("gate-test", ["AT-01", "AT-02"], [], 3))

    def test_blocked_node_makes_dependents_unreachable(self) -> None:
        text = replace_once(fixture_text("team-ok"), "- [ ] N1 ", "- [!] N1 ")
        text = replace_once(text, "- [ ] N2 ", "- [x] N2 ")
        data = checks.build_status(self.repo.parse("team-ok", text))
        self.assertEqual(data["ready"], [])
        self.assertEqual(data["unreachable"], ["N3", "G1", "G2"])
        self.assertEqual(data["counts"]["blocked"], 1)
        self.assertEqual([w["state"] for w in data["waves"]], ["closed", "pending", "pending", "pending"])
        self.assertIsNone(data["activeWave"])

    def test_active_wave_agrees_with_the_start_barrier(self) -> None:
        plan = self.repo.parse("team-ok", fixture_text("team-ok"))
        ids = [node.id for node in plan.nodes]
        for combination in itertools.product(("pending", "done", "blocked"), repeat=len(ids)):
            states = {ids[i]: combination[i] for i in range(len(ids))}
            _wave_states, active = checks.wave_progress(plan, states)
            unreachable = set(checks.unreachable_nodes(plan, states))
            for node in plan.nodes:
                if states[node.id] != "pending" or node.id in unreachable:
                    continue
                with self.subTest(states=states, node=node.id):
                    may_start = not checks.wave_blockers(plan, node, states)
                    self.assertEqual(may_start, active is not None and node.wave <= active)

    def test_base_requirements_and_record(self) -> None:
        text = replace_once(fixture_text("base-ok"), "| AT-02 | NOT_RUN | — | — |", "| AT-02 | FAIL | exit 0 | — |")
        data = checks.build_status(self.repo.parse("base-ok", text))
        self.assertEqual([(r["id"], r["happy"], r["other"]) for r in data["requirements"]], [("A1", ["AT-01"], ["AT-03"]), ("A2", ["AT-02"], [])])
        self.assertEqual([s["status"] for s in data["scenarios"]], ["NOT_RUN", "FAIL", "NOT_RUN"])
        self.assertEqual(data["ready"], ["T1", "T2"])
        self.assertEqual([n["wave"] for n in data["nodes"]], [1, 1])

    def test_workflow_state_declared(self) -> None:
        data = checks.build_status(self.repo.parse("workflow-ok", fixture_text("workflow-ok")))
        self.assertEqual(data["state"]["declared"], True)
        self.assertEqual(data["state"]["path"], "plan/workflow-ok.state.json")
        self.assertEqual(data["state"]["drift"], "missing")

    def test_legacy_status(self) -> None:
        data = checks.build_status(self.repo.parse("legacy-running", fixture_text("legacy-running")))
        self.assertEqual(data["legacy"]["done"], 1)
        self.assertEqual(len(data["legacy"]["open"]), 2)
        self.assertEqual(data["nodes"], [])


def forbidden_section(brief: str) -> list:
    section = brief.split("## Forbidden paths\n", 1)[1].split("\n## ", 1)[0]
    return [line[3:-1] for line in section.splitlines() if line.startswith("- `")]


SEQUENTIAL = """---
title: Same owner in sequence
slug: sequential
status: planning
created: 2026-11-12
tier: team
team: generic
review: pending
---

# Same owner in sequence

## Request
> "Split the parser and extend it later."

## Goal
The parser grows in two steps by one writer.

## Acceptance criteria
- [ ] A1 The parser reads headers
- [ ] A2 The parser reads quoted cells

## Scenarios
| Requirement | Happy path | Other checks | Not applicable (reason) |
| --- | --- | --- | --- |
| A1 | AT-01 | — | — |
| A2 | AT-02 | — | — |

### AT-01 — headers read
- Requirement: A1
- Preconditions / data: `fixtures/3rows.csv`
- Actions: `pytest tests/parser`
- Expected outcome: all tests pass
- Verification: pytest output
- Owners: implementer implementer; executor tester
- Evidence required: pytest summary

### AT-02 — quoted cells read
- Requirement: A2
- Preconditions / data: `fixtures/quoted.csv`
- Actions: `pytest tests/parser`
- Expected outcome: all tests pass
- Verification: pytest output
- Owners: implementer implementer; executor tester
- Evidence required: pytest summary

### Execution record
Candidate: —
| Scenario | Status | Observed result and evidence | Blocker |
| --- | --- | --- | --- |
| AT-01 | NOT_RUN | — | — |
| AT-02 | NOT_RUN | — | — |

## Team
| Role | Kind | Host agent | Notes |
| --- | --- | --- | --- |
| `main` | orchestrator | — | owns plan/ |
| `implementer` | writer | — | code and tests |
| `docs` | writer | — | documentation |
| `tester` | executor | — | runs scenarios |
| `reviewer` | reviewer | — | read-only |

## Tasks
### Wave 1: first step
- [ ] N1 Header parsing
  - owner: implementer
  - after: —
  - writes: `src/parser.py`, `tests/parser/**`
  - scenarios: AT-01
- [ ] D1 Parser page
  - owner: docs
  - after: —
  - writes: `docs/parser.md`
  - scenarios: AT-01

### Wave 2: second step
- [ ] N2 Quoted cells
  - owner: implementer
  - after: N1
  - writes: `src/parser.py`, `tests/parser/test_quoted.py`
  - scenarios: AT-02

### Wave 3: integration
- [ ] M1 Plan bookkeeping
  - owner: main
  - after: N2, D1
  - writes: `plan/**`, `CHANGELOG.md`
  - scenarios: AT-02

### Wave 4: acceptance
- [ ] G1 Run all scenarios
  - owner: tester
  - after: M1
  - writes: —
  - scenarios: all
  - gate: test

### Wave 5: review
- [ ] G2 Review
  - owner: reviewer
  - after: G1
  - writes: —
  - scenarios: —
  - gate: review

## Verification
- Tests: `pytest`

## Plan review

## Changes
(none)
"""


class BriefTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)
        self.plan = self.repo.parse("sequential", SEQUENTIAL)

    def test_sequential_plan_is_valid(self) -> None:
        errors = [f for f in checks.run_checks(self.plan, "draft") if f.severity == "error"]
        self.assertEqual(errors, [])

    def test_own_writes_never_forbidden(self) -> None:
        for node_id in ("N1", "N2"):
            with self.subTest(node=node_id):
                node = self.plan.node(node_id)
                forbidden = forbidden_section(checks.render_brief(self.plan, node))
                self.assertEqual(forbidden, checks.forbidden_paths(self.plan, node))
                for own in node.writes:
                    self.assertNotIn(own, forbidden)
                self.assertNotIn("src/parser.py", forbidden)
                self.assertIn("docs/parser.md", forbidden)
                self.assertIn("CHANGELOG.md", forbidden)
                self.assertIn("plan/**", forbidden)
                self.assertEqual(forbidden[-1], "plan/")

    def test_overlapping_patterns_of_other_nodes_are_dropped(self) -> None:
        forbidden = checks.forbidden_paths(self.plan, self.plan.node("N2"))
        self.assertNotIn("tests/parser/**", forbidden)
        self.assertEqual(forbidden, ["docs/parser.md", "plan/**", "CHANGELOG.md", "plan/"])

    def test_plan_dir_not_forbidden_for_a_node_that_writes_it(self) -> None:
        forbidden = checks.forbidden_paths(self.plan, self.plan.node("M1"))
        self.assertNotIn("plan/", forbidden)
        self.assertEqual(forbidden, ["src/parser.py", "tests/parser/**", "docs/parser.md", "tests/parser/test_quoted.py"])

    def test_workflow_brief_content(self) -> None:
        plan = self.repo.parse("workflow-ok", fixture_text("workflow-ok"))
        brief = checks.render_brief(plan, plan.node("N3"))
        for needle in (
            "A user can import orders from a CSV file.",
            "CSV columns map to order fields by header name.",
            "- consumes: `src/csv/parser.py`",
            "- produces: `src/api/import.py`",
            "returns 201 for 3rows.csv and 400 for noheader.csv",
            "### AT-01 — valid file creates orders",
            "### AT-02 — headerless file rejected",
            "## Report",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, brief)
        self.assertEqual(
            forbidden_section(brief),
            ["src/csv/**", "tests/csv/**", "src/orders/repo.py", "tests/orders/test_repo.py", "plan/"],
        )

    def test_wave_with_two_writers_defers_checks(self) -> None:
        brief = checks.render_brief(self.plan, self.plan.node("N1"))
        self.assertIn("Wave 1 has 2 writers: do not run builds or tests while writing", brief)
        brief = checks.render_brief(self.plan, self.plan.node("N2"))
        self.assertIn("You are the only writer in this wave", brief)


if __name__ == "__main__":
    unittest.main()
