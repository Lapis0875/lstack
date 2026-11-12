"""CLI: exit codes, envelopes and the acceptance scenario commands this node owns."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plan_loop_support import FIXTURES, REPO, SCRIPTS, TempRepo, fixture_text, replace_once, run_cli

ENVELOPE_KEYS = {"ok", "command", "plan", "tier", "status", "findings", "data"}


def fx(name: str) -> str:
    return str(FIXTURES / f"{name}.md")


def envelope(result) -> dict:
    data = json.loads(result.stdout)
    assert set(data) == ENVELOPE_KEYS, data
    return data


def error_codes(data: dict) -> list:
    return sorted({f["code"] for f in data["findings"] if f["severity"] == "error"})


class AcceptanceCommandTest(unittest.TestCase):
    """The commands of AT-01 step 1, AT-03, AT-05 to AT-09 and AT-17 step 1."""

    def test_at01_approve_check_passes(self) -> None:
        result = run_cli("--plan", fx("base-ok"), "check", "--phase", "approve")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("E-", result.stdout + result.stderr)

    def test_at03_requirements_have_happy_paths(self) -> None:
        data = envelope(run_cli("--json", "--plan", fx("base-ok"), "status"))["data"]
        self.assertEqual(
            ([(r["id"], bool(r["happy"])) for r in data["requirements"]], sorted(s["id"] for s in data["scenarios"])),
            ([("A1", True), ("A2", True)], ["AT-01", "AT-02", "AT-03"]),
        )

    def test_at05_waves(self) -> None:
        self.assertEqual(run_cli("--plan", fx("team-ok"), "check").returncode, 0)
        data = envelope(run_cli("--json", "--plan", fx("team-ok"), "waves"))["data"]
        self.assertEqual((data["waves"], data["matchesDeclared"]), ([["N1", "N2"], ["N3"], ["G1"], ["G2"]], True))

    def test_at06_to_at08_failing_fixtures(self) -> None:
        cases = {
            "team-cycle": "E-DAG-CYCLE",
            "team-unknown-dep": "E-DAG-UNKNOWN",
            "team-wave-order": "E-WAVE-ORDER",
            "team-no-owner": "E-NODE-FIELD",
            "team-bad-role": "E-TEAM-ROLE",
            "team-gate-owner": "E-GATE-OWNER",
            "team-unclaimed": "E-SCEN-UNCLAIMED",
            "team-overlap": "E-SCOPE-OVERLAP",
            "team-gate-wave": "E-GATE-WAVE",
        }
        for name, code in cases.items():
            with self.subTest(fixture=name):
                result = run_cli("--plan", fx(name), "check")
                self.assertEqual(result.returncode, 1)
                self.assertIn(code, result.stdout)

    def test_at07_owners(self) -> None:
        data = envelope(run_cli("--json", "--plan", fx("team-ok"), "status"))["data"]
        self.assertEqual(
            [(n["id"], n["owner"], n["ownerKind"]) for n in data["nodes"]],
            [("N1", "implementer", "writer"), ("N2", "implementer", "writer"), ("N3", "implementer", "writer"),
             ("G1", "tester", "executor"), ("G2", "reviewer", "reviewer")],
        )

    def test_at08_writes_and_scenarios(self) -> None:
        data = envelope(run_cli("--json", "--plan", fx("team-ok"), "status"))["data"]
        self.assertEqual(
            [(n["writes"], n["scenarios"]) for n in data["nodes"] if n["id"] == "N1"],
            [(["src/csv/**", "tests/csv/**"], ["AT-02"])],
        )

    def test_at09_workflow_brief(self) -> None:
        self.assertEqual(run_cli("--plan", fx("workflow-ok"), "check").returncode, 0)
        result = run_cli("--plan", fx("workflow-ok"), "brief", "N3")
        self.assertEqual(result.returncode, 0)
        for needle in (
            "A user can import orders from a CSV file.",
            "CSV columns map to order fields by header name.",
            "src/csv/parser.py",
            "src/api/import.py",
            "returns 201 for 3rows.csv and 400 for noheader.csv",
            "valid file creates orders",
            "headerless file rejected",
            "src/orders/repo.py",
            "plan/",
        ):
            with self.subTest(needle=needle):
                self.assertGreaterEqual(result.stdout.count(needle), 1)
        failing = run_cli("--plan", fx("workflow-no-donewhen"), "check")
        self.assertEqual(failing.returncode, 1)
        self.assertIn("E-BRIEF-FIELD", failing.stdout)

    def test_at17_copied_skill_runs_isolated(self) -> None:
        target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, target, True)
        shutil.copytree(SCRIPTS.parent, target / "plan-loop")
        script = target / "plan-loop" / "scripts" / "plan_loop.py"
        result = subprocess.run(
            [sys.executable, "-S", "-I", str(script), "--plan", fx("team-ok"), "check"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class OutputContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_check_envelope_and_text(self) -> None:
        data = envelope(run_cli("--json", "--plan", fx("base-no-happy"), "check"))
        self.assertFalse(data["ok"])
        self.assertEqual((data["command"], data["tier"], data["status"]), ("check", "base", "planning"))
        self.assertEqual(data["plan"], fx("base-no-happy"))
        self.assertEqual(data["data"], {"phase": "draft", "errors": 1, "warnings": 0})
        finding = data["findings"][0]
        self.assertEqual(set(finding), {"code", "severity", "message", "line", "node"})
        self.assertEqual((finding["code"], finding["severity"], finding["line"]), ("E-COVERAGE-HAPPY", "error", 29))
        self.assertIn("A2", finding["message"])
        text = run_cli("--plan", fx("base-no-happy"), "check")
        self.assertIn("tests/plan-loop/fixtures/base-no-happy.md:29: E-COVERAGE-HAPPY ", text.stdout)

    def test_scenario_field_names_the_scenario(self) -> None:
        result = run_cli("--plan", fx("base-scen-field"), "check")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stdout, r"E-SCEN-FIELD .*AT-02")

    def test_review_gate_codes(self) -> None:
        cases = {"base-no-review": ["E-REVIEW-MISSING"], "base-revise": ["E-REVIEW-OPEN", "E-REVIEW-VERDICT"], "base-waived": []}
        for name, expected in cases.items():
            with self.subTest(fixture=name):
                result = run_cli("--json", "--plan", fx(name), "check", "--phase", "approve")
                self.assertEqual(error_codes(envelope(result)), expected)
                self.assertEqual(result.returncode, 1 if expected else 0)

    def test_stale_review_after_edit(self) -> None:
        text = replace_once(fixture_text("base-ok"), "## Goal\n", "## Goal\nextra line\n")
        self.repo.write_plan("base-ok", text)
        result = run_cli("--json", "--cwd", str(self.repo.root), "check", "--phase", "approve")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(error_codes(envelope(result)), ["E-REVIEW-STALE"])

    def test_digest(self) -> None:
        full = run_cli("--plan", fx("team-ok"), "digest").stdout.strip()
        short = run_cli("--plan", fx("team-ok"), "digest", "--short").stdout.strip()
        self.assertRegex(full, r"^[0-9a-f]{64}$")
        self.assertEqual(short, full[:12])
        self.assertEqual(short, "e98147e968d8")
        data = envelope(run_cli("--json", "--plan", fx("team-ok"), "digest"))["data"]
        self.assertEqual(data, {"digest": full, "short": short})

    def test_waves_and_brief_need_a_team_plan(self) -> None:
        for command in (["waves"], ["brief", "T1"]):
            with self.subTest(command=command):
                result = run_cli("--json", "--plan", fx("base-ok"), *command)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(envelope(result)["ok"])
        self.assertEqual(run_cli("--plan", fx("legacy-running"), "waves").returncode, 2)

    def test_waves_cycle(self) -> None:
        result = run_cli("--json", "--plan", fx("team-cycle"), "waves")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(error_codes(envelope(result)), ["E-DAG-CYCLE"])

    def test_brief_unknown_node(self) -> None:
        result = run_cli("--plan", fx("team-ok"), "brief", "N9")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no node N9", result.stderr)

    def test_brief_json(self) -> None:
        data = envelope(run_cli("--json", "--plan", fx("team-ok"), "brief", "G1"))["data"]
        self.assertEqual(data["node"], "G1")
        self.assertIn("Run on the frozen candidate only.", data["text"])

    def test_no_active_plan(self) -> None:
        status = run_cli("--json", "--cwd", str(self.repo.root), "status")
        self.assertEqual(status.returncode, 0)
        data = envelope(status)
        self.assertEqual((data["ok"], data["plan"], data["tier"], data["status"], data["data"]), (True, None, None, None, {}))
        self.assertIn("no active plan", run_cli("--cwd", str(self.repo.root), "status").stdout)
        check = run_cli("--cwd", str(self.repo.root), "check")
        self.assertEqual(check.returncode, 2)
        self.assertIn("no active plan", check.stderr)

    def test_usage_errors(self) -> None:
        self.assertEqual(run_cli("frobnicate").returncode, 2)
        self.assertEqual(run_cli().returncode, 2)
        self.assertEqual(run_cli("check", "--phase", "later").returncode, 2)
        bad = run_cli("--json", "check", "--phase", "later")
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(envelope(bad)["ok"])
        self.assertEqual(run_cli("--plan", str(self.repo.root / "missing.md"), "check").returncode, 2)

    def test_status_from_nested_directory(self) -> None:
        self.repo.write_plan("legacy-running", fixture_text("legacy-running"))
        nested = self.repo.root / "src"
        nested.mkdir()
        data = envelope(run_cli("--json", "--cwd", str(nested), "status"))
        self.assertEqual((data["tier"], data["status"]), (None, "running"))
        self.assertEqual(data["data"]["legacy"]["done"], 1)
        self.assertEqual(len(data["data"]["legacy"]["open"]), 2)


class GuardStopCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {"TMPDIR": str(self.tmp)}

    def call(self, command: str, request: dict, *extra: str, env=None):
        environment = dict(self.env)
        environment.update(env or {})
        result = run_cli("--cwd", str(self.repo.root), *extra, command, "--request", json.dumps(request), env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return envelope(result)

    def test_guard_always_prints_the_envelope(self) -> None:
        self.repo.write_plan("legacy-planning", fixture_text("legacy-planning"))
        data = self.call("guard", {"cwd": str(self.repo.root), "tool": "shell", "command": "rm -rf src"})
        self.assertEqual(data["data"]["decision"], "deny")
        self.assertEqual(data["data"]["status"], "planning")
        self.assertTrue(data["data"]["reason"].startswith("plan-loop: legacy-planning.md is still in planning (read-only outside plan/)."))
        self.assertTrue(data["ok"])
        allowed = self.call("guard", {"tool": "write", "paths": ["plan/notes.md"]})
        self.assertEqual(allowed["data"], {"decision": "allow", "reason": "", "status": "planning"})
        blocked = self.call("guard", {"tool": "write", "paths": [], "label": "xd://resolve"})
        self.assertIn("Blocked xd://resolve.", blocked["data"]["reason"])

    def test_guard_without_plan_or_with_bad_request(self) -> None:
        data = self.call("guard", {"tool": "shell", "command": "rm -rf /"})
        self.assertEqual(data["data"], {"decision": "allow", "reason": "", "status": None})
        self.assertIsNone(data["plan"])
        raw = run_cli("--cwd", str(self.repo.root), "guard", "--request", "{not json")
        self.assertEqual(raw.returncode, 0)
        self.assertEqual(envelope(raw)["data"]["decision"], "allow")
        unknown = run_cli("guard", "--bogus")
        self.assertEqual(unknown.returncode, 0)
        self.assertEqual(envelope(unknown)["data"]["decision"], "allow")

    def test_stop_sequence_like_at21(self) -> None:
        self.repo.write_plan("team-ok", replace_once(fixture_text("team-ok"), "status: planning", "status: running"))
        first = self.call("stop", {"cwd": str(self.repo.root), "session_id": "at21-a"})["data"]
        self.assertEqual((first["decision"], first["next"]), ("continue", "N1"))
        decisions = [
            self.call("stop", {"cwd": str(self.repo.root), "session_id": "at21-e"}, env={"PLAN_LOOP_MAX_STALLS": "3"})["data"]["decision"]
            for _ in range(4)
        ]
        self.assertEqual(decisions, ["continue", "continue", "continue", "allow"])
        self.assertTrue((self.tmp / "plan-loop-stop" / "at21-e.json").is_file())

    def test_stop_after_blocked_node_and_scenarios(self) -> None:
        text = replace_once(fixture_text("team-ok"), "status: planning", "status: running")
        text = replace_once(text, "- [ ] N1 ", "- [!] N1 ")
        text = replace_once(text, "- [ ] N2 ", "- [x] N2 ")
        self.repo.write_plan("team-ok", text)
        self.assertEqual(self.call("stop", {"session_id": "at21-b"})["data"]["decision"], "allow")
        base = replace_once(fixture_text("base-ok"), "status: planning", "status: running").replace("- [ ] T", "- [x] T")
        self.repo.write_plan("base-ok", base)
        data = self.call("stop", {"session_id": "at21-c"})["data"]
        self.assertEqual((data["decision"], data["next"]), ("continue", None))
        self.repo.write_plan("base-ok", base.replace("| NOT_RUN |", "| PASS |"))
        self.assertEqual(self.call("stop", {"session_id": "at21-d"})["data"]["decision"], "allow")

    def test_stop_data_shape(self) -> None:
        data = self.call("stop", {"session_id": "nothing"})
        self.assertEqual(data["data"], {"decision": "allow", "reason": "", "next": None, "stalls": 0})
        bad = run_cli("stop", "--request", "[]", env=self.env)
        self.assertEqual(bad.returncode, 0)
        self.assertEqual(envelope(bad)["data"]["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
