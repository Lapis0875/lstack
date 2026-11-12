"""sync, advance, node and scenario through the CLI: gates, transitions, refusals, drift."""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import pathlib
import unittest
from pathlib import Path
from typing import Dict, Iterator, List, Tuple
from unittest import mock

from plan_loop_support import TempRepo, fixture_text, replace_once

import plan_loop  # noqa: E402  (plan_loop_support puts the scripts directory on sys.path)
from planlib import state as state_module  # noqa: E402

STATE_LINE = "review: pending\n"


def with_state(text: str, slug: str) -> str:
    """Declare a state document. The review digest changes, so the plan carries a user waiver."""
    text = replace_once(text, STATE_LINE, f"{STATE_LINE}state: plan/{slug}.state.json\n")
    return replace_once(text, "## Plan review\n", "## Plan review\n- Waived by user: 2026-11-12 — test plan\n")


class CliCase(unittest.TestCase):
    slug = "team-ok"
    text = ""
    explicit_plan = False  # pass --plan instead of discovering plan/ACTIVE from --cwd

    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)
        self.repo.write_plan(self.slug, self.text or fixture_text(self.slug))

    @property
    def plan_path(self) -> Path:
        return self.repo.root / "plan" / f"{self.slug}.md"

    @property
    def state_path(self) -> Path:
        return self.repo.root / "plan" / f"{self.slug}.state.json"

    def md(self) -> str:
        return self.plan_path.read_text(encoding="utf-8")

    def doc(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def snapshot(self) -> tuple:
        """Plan bytes, state document (bytes, a directory listing or None), plan/ACTIVE and plan/ entries."""
        if self.state_path.is_dir():
            state = ("directory", tuple(sorted(p.name for p in self.state_path.iterdir())))
        else:
            state = self.state_path.read_bytes() if self.state_path.exists() else None
        active = self.repo.root / "plan" / "ACTIVE"
        entries = tuple(sorted(p.name for p in (self.repo.root / "plan").iterdir()))
        return self.plan_path.read_bytes(), state, active.read_bytes() if active.exists() else None, entries

    def run_cli(self, *args: str) -> Tuple[int, dict, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            where = ["--plan", str(self.plan_path)] if self.explicit_plan else ["--cwd", str(self.repo.root)]
            code = plan_loop.main([*where, "--json", *args])
        envelope = json.loads(out.getvalue())
        self.assertEqual(envelope["ok"], code == 0)
        return code, envelope, err.getvalue()

    def ok(self, *args: str) -> dict:
        code, envelope, _ = self.run_cli(*args)
        self.assertEqual(code, 0, envelope)
        return envelope["data"]

    def refused(self, expected: int, *args: str) -> dict:
        before = self.snapshot()
        code, envelope, _ = self.run_cli(*args)
        self.assertEqual(code, expected, envelope)
        self.assertEqual(self.snapshot(), before, "a refused command changed a file")
        return envelope

    def unchanged(self, *args: str) -> dict:
        before = self.snapshot()
        data = self.ok(*args)
        self.assertEqual(self.snapshot(), before, "a no-op command changed a file")
        return data

    def codes(self, envelope: dict) -> set:
        return {f["code"] for f in envelope["findings"] if f["severity"] == "error"}

    def front(self, key: str) -> str:
        for line in self.md().split("\n"):
            if line.startswith(f"{key}:"):
                return line.split(":", 1)[1].strip()
        return ""


class AdvanceTest(CliCase):
    slug = "base-ok"

    def test_approve_writes_status_and_review(self) -> None:
        data = self.ok("advance", "approved")
        self.assertEqual(data, {"from": "planning", "to": "approved", "review": "passed", "activeRemoved": False, "requirementsTicked": []})
        self.assertEqual((self.front("status"), self.front("review")), ("approved", "passed"))
        self.unchanged("advance", "approved")

    def test_approve_refused_when_review_is_stale(self) -> None:
        self.plan_path.write_text(replace_once(self.md(), "## Goal\n", "## Goal\nextra line\n"), encoding="utf-8")
        envelope = self.refused(1, "advance", "approved")
        self.assertEqual(self.codes(envelope), {"E-REVIEW-STALE"})

    def test_running_needs_approval(self) -> None:
        self.refused(1, "advance", "running")
        self.ok("advance", "approved")
        self.assertEqual(self.ok("advance", "running")["from"], "approved")
        self.unchanged("advance", "running")
        self.refused(1, "advance", "approved")

    def test_done_gate_and_finish(self) -> None:
        self.refused(1, "advance", "done")
        self.ok("advance", "approved")
        self.ok("advance", "running")
        envelope = self.refused(1, "advance", "done")
        self.assertEqual(self.codes(envelope), {"E-FINISH-OPEN", "E-FINISH-SCEN"})
        self.ok("node", "done", "T1")
        self.ok("node", "done", "T2")
        for scenario in ("AT-01", "AT-02"):
            self.ok("scenario", "record", scenario, "PASS", "--evidence", "ok")
        self.ok("scenario", "record", "AT-03", "FAIL", "--evidence", "trailing space lost")
        self.assertEqual(self.codes(self.refused(1, "advance", "done")), {"E-FINISH-SCEN"})
        self.ok("scenario", "record", "AT-03", "PASS", "--evidence", "fixed", "--candidate", "c2")
        data = self.ok("advance", "done")
        self.assertEqual(data["requirementsTicked"], ["A1", "A2"])
        self.assertTrue(data["activeRemoved"])
        self.assertFalse((self.repo.root / "plan" / "ACTIVE").exists())
        self.assertIn("- [x] A1 ", self.md())
        self.assertIn("Candidate: c2", self.md())
        self.explicit_plan = True  # plan/ACTIVE is gone; address the plan directly
        self.unchanged("advance", "done")

    def test_abandon_from_any_status(self) -> None:
        data = self.ok("advance", "abandoned")
        self.assertTrue(data["activeRemoved"])
        self.assertEqual(self.front("status"), "abandoned")

    def test_active_left_alone_when_it_names_another_plan(self) -> None:
        (self.repo.root / "plan" / "ACTIVE").write_text("other\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = plan_loop.main(["--plan", str(self.plan_path), "--json", "advance", "abandoned"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["data"]["activeRemoved"])
        self.assertTrue((self.repo.root / "plan" / "ACTIVE").exists())


class WaivedAdvanceTest(CliCase):
    slug = "base-waived"

    def test_waiver_sets_review_waived(self) -> None:
        self.assertEqual(self.ok("advance", "approved")["review"], "waived")
        self.assertEqual(self.front("review"), "waived")


class LegacyTest(CliCase):
    slug = "legacy-running"

    def test_advance_edits_status_only(self) -> None:
        envelope = self.refused(1, "advance", "done")
        self.assertEqual(self.codes(envelope), {"E-FINISH-OPEN"})
        before = self.md()
        self.ok("advance", "abandoned")
        after = self.md()
        self.assertEqual(after, before.replace("status: running", "status: abandoned"))
        self.assertTrue((self.repo.root / "plan" / "ACTIVE").exists())

    def test_other_commands_refused(self) -> None:
        for args in (("sync",), ("node", "done", "T2"), ("node", "start", "T2"), ("scenario", "record", "AT-01", "PASS", "--evidence", "x")):
            with self.subTest(args=args):
                self.refused(2, *args)


class NoStateNodeTest(CliCase):
    """Part 2 E table, column without state:, on a team plan."""

    def test_done_respects_after_and_is_idempotent(self) -> None:
        self.assertIn("waits on N1 (pending), N2 (pending)", self.refused(4, "node", "done", "N3")["data"]["error"])
        data = self.ok("node", "done", "N1", "--evidence", "pytest ok")
        self.assertTrue(data["planEdited"])
        self.assertEqual((data["node"]["id"], data["node"]["state"], data["node"]["mark"]), ("N1", "done", "x"))
        self.assertIn("- [x] N1 ", self.md())
        self.assertIn("  - check: `pytest tests/csv`\n  - evidence: pytest ok\n- [ ] N2", self.md())
        again = self.unchanged("node", "done", "N1")
        self.assertFalse(again["planEdited"])

    def test_block_and_reset(self) -> None:
        self.refused(2, "node", "block", "N1")
        data = self.ok("node", "block", "N1", "--reason", "no access")
        self.assertEqual(data["node"]["state"], "blocked")
        self.assertIn("- [!] N1 ", self.md())
        self.assertIn("  - blocked: no access\n", self.md())
        self.assertFalse(self.unchanged("node", "block", "N1", "--reason", "again")["planEdited"])
        self.refused(4, "node", "done", "N1")
        self.ok("node", "reset", "N1")
        self.assertIn("- [ ] N1 ", self.md())
        self.assertNotIn("blocked:", self.md())
        self.unchanged("node", "reset", "N1")

    def test_reset_cascade(self) -> None:
        for node in ("N1", "N2", "N3"):
            self.ok("node", "done", node)
        data = self.ok("node", "reset", "N1", "--cascade")
        self.assertEqual(data["cascaded"], ["N3"])
        self.assertIn("- [ ] N1 ", self.md())
        self.assertIn("- [x] N2 ", self.md())
        self.assertIn("- [ ] N3 ", self.md())

    def test_state_only_actions_refused(self) -> None:
        for action in ("start", "claim", "fail"):
            with self.subTest(action=action):
                envelope = self.refused(2, "node", action, "N1")
                self.assertEqual(envelope["data"]["error"], "requires a state document (front matter state:)")
        self.refused(2, "sync")
        self.refused(2, "node", "done", "N9")

    def test_test_gate_needs_recorded_scenarios(self) -> None:
        for node in ("N1", "N2", "N3"):
            self.ok("node", "done", node)
        self.assertIn("NOT_RUN", self.refused(4, "node", "done", "G1")["data"]["error"])
        self.ok("scenario", "record", "AT-01", "PASS", "--evidence", "201")
        self.refused(4, "node", "done", "G1")
        self.ok("scenario", "record", "AT-02", "FAIL", "--evidence", "500", "--blocker", "parser bug")
        self.ok("node", "done", "G1")
        self.assertIn("| AT-02 | FAIL | 500 | parser bug |", self.md())

    def test_scenario_record(self) -> None:
        data = self.ok("scenario", "record", "AT-01", "BLOCKED", "--evidence", "no db", "--candidate", "c1", "--blocker", "db down")
        self.assertEqual(data, {"scenario": {"id": "AT-01", "status": "BLOCKED", "candidate": "c1", "evidence": "no db", "blocker": "db down"}, "planEdited": True})
        self.assertIn("Candidate: c1\n", self.md())
        self.assertIn("| AT-01 | BLOCKED | no db | db down |", self.md())
        self.refused(2, "scenario", "record", "AT-09", "PASS", "--evidence", "x")
        self.refused(2, "scenario", "record", "AT-01", "PASS", "--evidence", "a | b")
        self.refused(2, "scenario", "record", "AT-01", "PASS", "--evidence", "two\nlines")
        self.refused(2, "scenario", "record", "AT-01", "SKIPPED", "--evidence", "x")


class StatefulCase(CliCase):
    slug = "workflow-ok"

    def setUp(self) -> None:
        super().setUp()
        self.ok("advance", "approved")
        self.ok("advance", "running")


class WorkflowNodeTest(StatefulCase):
    def test_state_document_created_on_approval(self) -> None:
        doc = self.doc()
        self.assertEqual(doc["plan"]["status"], "running")
        self.assertEqual(doc["plan"]["review"], "passed")
        self.assertEqual([e["type"] for e in doc["events"]], ["synced", "plan.status", "plan.status"])
        self.assertEqual([e["data"]["to"] for e in doc["events"][1:]], ["approved", "running"])

    def test_start_claim_done(self) -> None:
        self.refused(4, "node", "start", "N3")
        self.refused(4, "node", "claim", "N1", "--agent", "a1")
        self.ok("node", "start", "N1", "--by", "main")
        self.unchanged("node", "start", "N1")
        self.ok("node", "claim", "N1", "--agent", "a1", "--provider", "p", "--model", "m", "--effort", "high", "--evidence", "src/csv")
        self.refused(4, "node", "done", "N1")
        self.refused(4, "node", "done", "N1", "--by", "a1")
        data = self.ok("node", "done", "N1", "--by", "main", "--evidence", "pytest ok")
        self.assertEqual(data["node"]["state"], "done")
        entry = next(n for n in self.doc()["nodes"] if n["id"] == "N1")
        self.assertEqual(entry["executor"], {"agent": "a1", "provider": "p", "model": "m", "effort": "high"})
        self.assertEqual((entry["confirmedBy"], entry["evidence"]), ("main", ["src/csv", "pytest ok"]))
        self.assertIsNotNone(entry["startedAt"])
        self.assertIsNotNone(entry["finishedAt"])
        types = [e["type"] for e in self.doc()["events"]][3:]
        self.assertEqual(types, ["node.started", "node.claimed", "node.done"])
        seqs = [e["seq"] for e in self.doc()["events"]]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_fail_until_blocked(self) -> None:
        self.ok("node", "start", "N2")
        data = self.ok("node", "fail", "N2", "--reason", "flaky")
        self.assertFalse(data["planEdited"])
        self.assertEqual(data["node"]["state"], "pending")
        self.assertEqual(next(n for n in self.doc()["nodes"] if n["id"] == "N2")["attempt"], 1)
        self.refused(4, "node", "fail", "N2")
        self.ok("node", "start", "N2")
        data = self.ok("node", "fail", "N2", "--reason", "still flaky")
        self.assertTrue(data["planEdited"])
        self.assertEqual(data["node"]["state"], "blocked")
        self.assertIn("- [!] N2 ", self.md())
        self.assertIn("  - blocked: still flaky\n", self.md())
        status = self.ok("status")
        self.assertEqual(status["unreachable"], ["N3", "G1", "G2"])

    def test_scenario_record_updates_the_state_document(self) -> None:
        self.ok("scenario", "record", "AT-02", "PASS", "--evidence", "curl 400", "--candidate", "c1", "--by", "main")
        entry = next(s for s in self.doc()["scenarios"] if s["id"] == "AT-02")
        self.assertEqual((entry["status"], entry["candidate"], entry["evidence"]), ("PASS", "c1", "curl 400"))
        self.assertIsNotNone(entry["recordedAt"])
        event = self.doc()["events"][-1]
        self.assertEqual((event["type"], event["scenario"], event["by"]), ("scenario.recorded", "AT-02", "main"))
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_fail_reason_with_separators(self) -> None:
        """G4 F7: the blocked reason written by node fail stays one free-text field."""
        reason = "flaky — check: rerun later — owner: reviewer"
        before = self.md()
        for _ in range(2):
            self.ok("node", "start", "N2")
            self.ok("node", "fail", "N2", "--reason", reason)
        self.assertIn(f"  - check: `pytest tests/orders/test_repo.py`\n  - blocked: {reason}\n", self.md())
        from planlib import planfile

        node = planfile.parse_plan(self.repo.root, self.plan_path).node("N2")
        self.assertEqual((node.mark, node.fields["blocked"], node.fields["check"], node.owner, node.issues), (
            "!", reason, "`pytest tests/orders/test_repo.py`", "implementer", [],
        ))
        self.assertEqual(self.run_cli("check")[0], 0)
        self.ok("node", "reset", "N2")
        self.assertEqual(self.md(), before)

    def test_reset_keeps_attempts(self) -> None:
        for _ in range(2):
            self.ok("node", "start", "N2")
            self.ok("node", "fail", "N2")
        self.ok("node", "reset", "N2")
        entry = next(n for n in self.doc()["nodes"] if n["id"] == "N2")
        self.assertEqual((entry["state"], entry["attempt"]), ("pending", 2))
        self.assertIn("- [ ] N2 ", self.md())
        self.assertNotIn("blocked:", self.md())

    def test_reset_of_running_node_refused(self) -> None:
        self.ok("node", "start", "N1")
        self.refused(4, "node", "reset", "N1")

    def test_hand_edit_is_stale_until_sync(self) -> None:
        self.plan_path.write_text(replace_once(self.md(), "- [ ] N2 ", "- [x] N2 "), encoding="utf-8")
        code, envelope, _ = self.run_cli("status")
        self.assertEqual((code, envelope["data"]["state"]["drift"]), (3, "stale"))
        self.assertEqual([n["state"] for n in envelope["data"]["nodes"]][:2], ["pending", "done"])
        code, envelope, _ = self.run_cli("check")
        self.assertEqual((code, self.codes(envelope)), (3, {"E-STATE-STALE"}))
        data = self.ok("sync")
        self.assertEqual((data["created"], data["reconciled"], data["path"]), (False, ["N2"], "plan/workflow-ok.state.json"))
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_missing_and_invalid_state(self) -> None:
        self.state_path.unlink()
        code, envelope, _ = self.run_cli("check")
        self.assertEqual((code, self.codes(envelope)), (3, {"E-STATE-MISSING"}))
        self.assertEqual(self.run_cli("status")[0], 3)
        self.refused(2, "node", "start", "N1")
        self.assertTrue(self.ok("sync")["created"])
        self.state_path.write_text("{}", encoding="utf-8")
        code, envelope, _ = self.run_cli("check")
        self.assertEqual((code, self.codes(envelope)), (1, {"E-STATE-SCHEMA"}))
        self.assertEqual(self.run_cli("status")[1]["data"]["state"]["drift"], "invalid")
        self.assertEqual(self.codes(self.refused(1, "node", "block", "N1", "--reason", "x")), {"E-STATE-SCHEMA"})
        self.refused(1, "sync")
        self.ok("advance", "abandoned")
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "{}")


class TeamStateTest(StatefulCase):
    slug = "team-ok"
    text = with_state(fixture_text("team-ok"), "team-ok")

    def test_team_done_without_claim(self) -> None:
        self.ok("node", "done", "N1")
        self.assertEqual(next(n for n in self.doc()["nodes"] if n["id"] == "N1")["state"], "done")

    def test_definition_change_makes_downstream_stale(self) -> None:
        self.ok("node", "done", "N1")
        self.plan_path.write_text(replace_once(self.md(), "  - check: `pytest tests/csv`", "  - check: `pytest -x tests/csv`"), encoding="utf-8")
        data = self.ok("sync")
        self.assertEqual((data["stale"], data["revision"]), (["N1", "N3", "G1", "G2"], 2))
        code, envelope, _ = self.run_cli("check")
        self.assertEqual((code, self.codes(envelope)), (1, {"E-STATE-NODE-STALE"}))
        self.assertEqual(self.ok("status")["state"]["staleNodes"], ["N1", "N3", "G1", "G2"])
        data = self.ok("node", "reset", "N1", "--cascade")
        self.assertEqual(data["cascaded"], ["N3", "G1", "G2"])
        self.assertEqual([n["stale"] for n in self.doc()["nodes"]], [False] * 5)
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_wave_order_on_start(self) -> None:
        self.plan_path.write_text(replace_once(self.md(), "  - after: N1, N2", "  - after: N1"), encoding="utf-8")
        self.ok("sync")
        self.ok("node", "done", "N1")
        self.assertIn("earlier waves are still open: N2", self.refused(4, "node", "start", "N3")["data"]["error"])
        self.ok("node", "block", "N2", "--reason", "no db")
        self.ok("node", "start", "N3")


class GateStartTest(StatefulCase):
    slug = "team-gate-wave"
    text = with_state(fixture_text("team-gate-wave"), "team-gate-wave")

    def setUp(self) -> None:
        CliCase.setUp(self)
        self.ok("sync")

    def test_gate_waits_for_running_nodes(self) -> None:
        self.ok("node", "start", "N1")
        self.assertIn("running or claimed", self.refused(4, "node", "start", "G3")["data"]["error"])
        self.ok("node", "fail", "N1")
        self.ok("node", "start", "G3")


class StopAfterChangesTest(CliCase):
    """AT-21 steps 1 and 2 through the CLI, with stall files in a temporary directory."""

    def setUp(self) -> None:
        super().setUp()
        from unittest import mock

        from planlib import guards

        patcher = mock.patch.object(guards, "STATE_DIR", self.repo.base / "plan-loop-stop")
        patcher.start()
        self.addCleanup(patcher.stop)

    def stop(self, session: str) -> dict:
        request = json.dumps({"cwd": str(self.repo.root), "session_id": session})
        return self.ok("stop", "--request", request)

    def test_blocked_node_releases_the_stop(self) -> None:
        self.ok("advance", "approved")
        self.ok("advance", "running")
        first = self.stop("a")
        self.assertEqual((first["decision"], first["next"]), ("continue", "N1"))
        self.ok("node", "block", "N1", "--reason", "no access")
        self.ok("node", "done", "N2")
        self.assertEqual(self.stop("b")["decision"], "allow")


class EnvelopeTest(StatefulCase):
    def test_node_and_sync_data_shapes(self) -> None:
        data: Dict = self.ok("node", "start", "N1")
        self.assertEqual(set(data), {"action", "node", "planEdited", "cascaded"})
        self.assertEqual(set(data["node"]), {"id", "title", "mark", "kind", "owner", "ownerKind", "after", "writes", "scenarios", "wave", "line", "state", "ready"})
        self.assertEqual(data["node"]["state"], "running")
        sync = self.ok("sync")
        self.assertEqual(set(sync), {"path", "created", "revision", "reconciled", "stale"})

    def test_text_mode_messages(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = plan_loop.main(["--cwd", str(self.repo.root), "node", "start", "G1"])
        self.assertEqual(code, 4)
        self.assertIn("plan_loop: error: G1 waits on N3 (pending)", err.getvalue())


@contextlib.contextmanager
def failing_replace(*calls: int) -> Iterator[List[str]]:
    """Make the given os.replace calls (1-based) fail, as a full disk or a lost mount would."""
    real = os.replace
    seen: List[str] = []

    def replace(src, dst):
        seen.append(str(dst))
        if len(seen) in calls:
            raise OSError(errno.EIO, "injected write failure", str(dst))
        return real(src, dst)

    with mock.patch.object(state_module.os, "replace", replace):
        yield seen


class WriteSafetyTest(CliCase):
    """G2 F1: a command that fails while writing leaves the plan, the state document and plan/ACTIVE as they were."""

    slug = "workflow-ok"

    def test_directory_in_place_of_the_state_document(self) -> None:
        self.state_path.mkdir()
        (self.state_path / "keep").write_text("x", encoding="utf-8")
        for args in (
            ("advance", "approved"),
            ("node", "block", "N1", "--reason", "no access"),
            ("node", "done", "N1", "--by", "main"),
            ("scenario", "record", "AT-01", "PASS", "--evidence", "ok"),
            ("sync",),
        ):
            with self.subTest(args=args):
                envelope = self.refused(2, *args)
                self.assertIn("is not a regular file", envelope["data"]["error"])
        self.assertEqual(self.front("status"), "planning")
        code, envelope, _ = self.run_cli("status")
        self.assertEqual((code, envelope["data"]["state"]["drift"]), (0, "invalid"))

    def test_state_write_fails_on_first_approval(self) -> None:
        with failing_replace(2) as seen:
            envelope = self.refused(2, "advance", "approved")
        self.assertEqual([Path(p).name for p in seen], ["workflow-ok.md", "workflow-ok.state.json", "workflow-ok.md"])
        self.assertIn("injected write failure", envelope["data"]["error"])
        self.assertEqual((self.front("status"), self.front("review")), ("planning", "pending"))
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.ok("advance", "approved")["review"], "passed")

    def test_second_write_failure_restores_the_plan(self) -> None:
        self.ok("advance", "approved")
        self.ok("advance", "running")
        for args in (
            ("node", "block", "N1", "--reason", "no access"),
            ("scenario", "record", "AT-01", "PASS", "--evidence", "ok", "--candidate", "c1"),
            ("advance", "abandoned"),
        ):
            with self.subTest(args=args), failing_replace(2):
                self.refused(2, *args)
        self.assertEqual(self.front("status"), "running")

    def test_sync_write_failure_keeps_the_state_document(self) -> None:
        self.ok("advance", "approved")
        self.ok("advance", "running")
        self.plan_path.write_text(replace_once(self.md(), "- [ ] N2 ", "- [x] N2 "), encoding="utf-8")
        with failing_replace(1):
            self.refused(2, "sync")
        self.assertEqual(self.ok("sync")["reconciled"], ["N2"])

    def test_active_removal_failure_restores_both_files(self) -> None:
        self.ok("advance", "approved")
        self.ok("advance", "running")
        real = pathlib.Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "ACTIVE":
                raise PermissionError(errno.EACCES, "injected", str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "unlink", unlink):
            self.refused(2, "advance", "abandoned")

    def test_failed_restore_is_reported(self) -> None:
        self.ok("advance", "approved")
        self.ok("advance", "running")
        with failing_replace(2, 3):
            code, envelope, _ = self.run_cli("node", "block", "N1", "--reason", "no access")
        self.assertEqual(code, 2)
        self.assertIn("could not restore plan/workflow-ok.md", envelope["data"]["error"])


class WorkflowClaimTest(StatefulCase):
    """G2 F2: a workflow claim names its agent, and done needs a recorded agent to compare against."""

    def test_claim_needs_a_non_empty_agent(self) -> None:
        self.ok("node", "start", "N1")
        for extra in ((), ("--agent", ""), ("--agent", "   ")):
            with self.subTest(extra=extra):
                envelope = self.refused(2, "node", "claim", "N1", "--model", "m", *extra)
                self.assertIn("--agent", envelope["data"]["error"])
        self.ok("node", "claim", "N1", "--agent", "a1")
        self.refused(4, "node", "done", "N1", "--by", "a1")
        self.ok("node", "done", "N1", "--by", "main")

    def test_done_refused_when_the_claim_has_no_agent(self) -> None:
        self.ok("node", "start", "N1")
        self.ok("node", "claim", "N1", "--agent", "a1")
        doc = self.doc()
        for entry in doc["nodes"]:
            if entry["id"] == "N1":
                entry["executor"]["agent"] = None
        self.state_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        envelope = self.refused(4, "node", "done", "N1", "--by", "main")
        self.assertIn("without an agent", envelope["data"]["error"])


BRANCHES = """---
title: Two branches
slug: branches
status: planning
created: 2026-11-12
tier: team
team: generic
review: pending
state: plan/branches.state.json
---

# Two branches

## Request
> "Ship the parser and the exporter independently."

## Goal
The parser and the exporter ship on separate branches of the graph.

## Acceptance criteria
- [ ] A1 The parser reads a file
- [ ] A2 The exporter writes a file

## Scenarios
| Requirement | Happy path | Other checks | Not applicable (reason) |
| --- | --- | --- | --- |
| A1 | AT-01 | — | — |
| A2 | AT-02 | — | — |

### AT-01 — parser reads
- Requirement: A1
- Preconditions / data: `fixtures/in.csv`
- Actions: `pytest tests/parser`
- Expected outcome: all tests pass
- Verification: pytest output
- Owners: implementer implementer; executor tester
- Evidence required: pytest summary

### AT-02 — exporter writes
- Requirement: A2
- Preconditions / data: `fixtures/out.csv`
- Actions: `pytest tests/export`
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
| `tester` | executor | — | runs scenarios |
| `reviewer` | reviewer | — | read-only |

## Tasks
### Wave 1: foundations
- [ ] N1 Parser core
  - owner: implementer
  - after: —
  - writes: `src/parser/**`
  - scenarios: AT-01
- [ ] N2 Exporter core
  - owner: implementer
  - after: —
  - writes: `src/export/core.py`
  - scenarios: AT-02

### Wave 2: parser branch
- [ ] N3 Parser options
  - owner: implementer
  - after: N1
  - writes: `src/cli/parse.py`
  - scenarios: AT-01

### Wave 3: exporter branch
- [ ] N4 Exporter formats
  - owner: implementer
  - after: N2
  - writes: `src/export/formats.py`
  - scenarios: AT-02

### Wave 4: acceptance
- [ ] G1 Run all scenarios
  - owner: tester
  - after: N3, N4
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
- Waived by user: 2026-11-12 — test plan

## Changes
(none)
"""


class BranchWavesTest(StatefulCase):
    """G2 F5: the active wave is the wave whose nodes the start barrier lets run."""

    slug = "branches"
    text = BRANCHES

    def test_unreachable_wave_is_passed_over(self) -> None:
        self.assertEqual(self.run_cli("check")[0], 0)
        status = self.ok("status")
        self.assertEqual((status["activeWave"], [w["state"] for w in status["waves"]]), (1, ["active", "pending", "pending", "pending", "pending"]))
        self.ok("node", "block", "N1", "--reason", "no access")
        self.ok("node", "done", "N2")
        status = self.ok("status")
        expected = ["closed", "pending", "active", "pending", "pending"]
        self.assertEqual(status["unreachable"], ["N3", "G1", "G2"])
        self.assertEqual((status["activeWave"], [w["state"] for w in status["waves"]]), (3, expected))
        self.assertEqual([w["state"] for w in self.doc()["waves"]], expected)
        self.refused(4, "node", "start", "N3")
        self.ok("node", "start", "N4")
        self.ok("node", "done", "N4")
        status = self.ok("status")
        self.assertEqual((status["activeWave"], [w["state"] for w in status["waves"]]), (None, ["closed", "pending", "closed", "pending", "pending"]))
        self.assertEqual([w["state"] for w in self.doc()["waves"]], ["closed", "pending", "closed", "pending", "pending"])


if __name__ == "__main__":
    unittest.main()
