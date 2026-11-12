"""Tool and stop decisions: legacy behavior equals the original hooks; tier stop rules."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hook_reference
from plan_loop_support import TempRepo, fixture_text, replace_once

from planlib import guards, planfile

PATCH_ADD = "*** Begin Patch\n*** Add File: src/a.txt\n+hi\n*** End Patch"
PATCHES = [
    PATCH_ADD,
    "*** Begin Patch\n*** Update File: plan/notes.md\n@@\n+x\n*** End Patch",
    "*** Begin Patch\n*** Update File: plan/notes.md\n*** Move to: src/notes.md\n*** End Patch",
    "*** Begin Patch\n*** Delete File: ../outside.txt\n*** Add File: plan/a.md\n+x\n*** End Patch",
    "no patch markers at all",
]
COMMANDS = [
    "rm -rf src",
    "ls -la",
    "cat README.md | grep x",
    "echo hi > plan/x.md",
    "echo hi > x.md",
    "echo hi >> notes.txt 2>/dev/null",
    "git status && git commit -m x",
    "npm install left-pad",
    "sed -i s/a/b/ f",
    "python3 -c 'print(1)' > /dev/null",
    "grep -r foo . 2>&1",
    "make build",
]
PREFIX = "plan-loop: {name} is still in planning (read-only outside plan/)."


class ToolDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def compare_with_original(self, slug: str) -> None:
        self.repo.write_plan(slug, fixture_text(slug))
        cwd = str(self.repo.root)
        plan = planfile.find_active_plan(cwd)
        events = [("apply_patch", "patch", body) for body in PATCHES] + [("Bash", "shell", cmd) for cmd in COMMANDS]
        for hook_tool, tool, command in events:
            with self.subTest(slug=slug, tool=hook_tool, command=command):
                expected = hook_reference.guard({"cwd": cwd, "tool_name": hook_tool, "tool_input": {"command": command}})
                allow, reason = guards.decide_tool(plan, cwd, tool, command=command)
                if expected:
                    self.assertFalse(allow)
                    self.assertEqual(reason, expected["hookSpecificOutput"]["permissionDecisionReason"])
                else:
                    self.assertEqual((allow, reason), (True, ""))

    def test_legacy_plan_matches_original_hook(self) -> None:
        self.compare_with_original("legacy-planning")

    def test_tier_plan_shell_and_patch_reasons_match_original_hook(self) -> None:
        self.compare_with_original("team-ok")

    def test_known_reasons(self) -> None:
        self.repo.write_plan("legacy-planning", fixture_text("legacy-planning"))
        cwd = str(self.repo.root)
        plan = planfile.find_active_plan(cwd)
        prefix = PREFIX.format(name="legacy-planning.md")
        self.assertEqual(
            guards.decide_tool(plan, cwd, "patch", command=PATCH_ADD),
            (False, f"{prefix} Blocked edit to: src/a.txt. Finish the plan and get approval first."),
        )
        self.assertEqual(
            guards.decide_tool(plan, cwd, "shell", command="rm -rf src"),
            (False, f"{prefix} This shell command looks mutating. Use read-only commands until the plan is approved."),
        )

    def test_write_kind(self) -> None:
        self.repo.write_plan("team-ok", fixture_text("team-ok"))
        cwd = str(self.repo.root)
        plan = planfile.find_active_plan(cwd)
        prefix = PREFIX.format(name="team-ok.md")
        tail = "Finish the plan and get approval first."
        cases = [
            ((["plan/notes.md"],), None, (True, "")),
            ((["plan/a.md", "plan/*.md", "plan/sub/**"],), None, (True, "")),
            ((["src/x.py"],), None, (False, f"{prefix} Blocked src/x.py. {tail}")),
            ((["plan/a.md", "src/x.py", "README.md"],), None, (False, f"{prefix} Blocked src/x.py, README.md. {tail}")),
            (([],), "xd://resolve", (False, f"{prefix} Blocked xd://resolve. {tail}")),
            (([],), None, (False, f"{prefix} Blocked a change with no known target path. {tail}")),
            ((["src/**"],), "lsp rename", (False, f"{prefix} Blocked lsp rename. {tail}")),
            ((["*.md"],), None, (False, f"{prefix} Blocked *.md. {tail}")),
            (([f"file://{self.repo.root}/plan/x.md"],), None, (True, "")),
            (([str(self.repo.root / "src" / "y.py")],), None, (False, f"{prefix} Blocked {self.repo.root / 'src' / 'y.py'}. {tail}")),
        ]
        for (paths,), label, expected in cases:
            with self.subTest(paths=paths, label=label):
                self.assertEqual(guards.decide_tool(plan, cwd, "write", paths=paths, label=label), expected)

    def test_relative_to_a_nested_cwd(self) -> None:
        self.repo.write_plan("team-ok", fixture_text("team-ok"))
        nested = self.repo.root / "plan"
        plan = planfile.find_active_plan(str(nested))
        self.assertEqual(guards.decide_tool(plan, str(nested), "write", paths=["notes.md"]), (True, ""))
        self.assertFalse(guards.decide_tool(plan, str(nested), "write", paths=["../src/a.py"])[0])

    def test_only_planning_restricts(self) -> None:
        text = replace_once(fixture_text("team-ok"), "status: planning", "status: running")
        self.repo.write_plan("team-ok", text)
        cwd = str(self.repo.root)
        plan = planfile.find_active_plan(cwd)
        for tool, kwargs in (("shell", {"command": "rm -rf src"}), ("patch", {"command": PATCH_ADD}), ("write", {"paths": []})):
            with self.subTest(tool=tool):
                self.assertEqual(guards.decide_tool(plan, cwd, tool, **kwargs), (True, ""))
        self.assertEqual(guards.decide_tool(None, cwd, "write", paths=[]), (True, ""))

    def test_unknown_tool_is_allowed(self) -> None:
        self.repo.write_plan("team-ok", fixture_text("team-ok"))
        plan = planfile.find_active_plan(str(self.repo.root))
        self.assertEqual(guards.decide_tool(plan, str(self.repo.root), "eval", command="rm -rf /"), (True, ""))


class StopTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)
        self.state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state_dir, True)
        patcher = mock.patch.object(guards, "STATE_DIR", self.state_dir / "plan-loop-stop")
        patcher.start()
        self.addCleanup(patcher.stop)

    def load(self, slug: str, text: str) -> planfile.Plan:
        self.repo.write_plan(slug, text)
        return planfile.find_active_plan(str(self.repo.root))


class LegacyStopTest(StopTestBase):
    def test_sequence_matches_original_hook(self) -> None:
        reference_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, reference_dir, True)
        text = fixture_text("legacy-running")
        self.repo.write_plan("legacy-running", text)
        cwd = str(self.repo.root)
        steps = [text, text, text, replace_once(text, "- [ ] T2 ", "- [x] T2 "), None, None, None, None, None, None]
        current = text
        for index, step in enumerate(steps):
            if step is not None:
                current = step
                self.repo.write_plan("legacy-running", current)
            with self.subTest(step=index):
                expected = hook_reference.stop({"cwd": cwd, "session_id": "s-1"}, reference_dir / "s", 3)
                plan = planfile.find_active_plan(cwd)
                allow, reason = guards.decide_stop(plan, "s-1", max_stalls=3)
                if expected:
                    self.assertEqual((allow, reason), (False, expected["reason"]))
                else:
                    self.assertTrue(allow)
                ours = json.loads((self.state_dir / "plan-loop-stop" / "s-1.json").read_text(encoding="utf-8"))
                theirs = json.loads((reference_dir / "s" / "s-1.json").read_text(encoding="utf-8"))
                self.assertEqual(ours, theirs)

    def test_reason_and_state_file_format(self) -> None:
        plan = self.load("legacy-running", fixture_text("legacy-running"))
        decision = guards.evaluate_stop(plan, "abc/../x y", max_stalls=5)
        self.assertFalse(decision.allow)
        self.assertIn("2 open task(s)", decision.reason)
        self.assertTrue(decision.reason.startswith("plan-loop: plan/legacy-running.md is running with 2 open task(s). Next: T2 "))
        saved = (self.state_dir / "plan-loop-stop" / "abcxy.json").read_text(encoding="utf-8")
        self.assertEqual(saved, json.dumps({"plan": str(plan.path), "done": 1, "stalls": 0}))

    def test_not_running_or_nothing_open(self) -> None:
        plan = self.load("legacy-planning", fixture_text("legacy-planning"))
        self.assertEqual(guards.decide_stop(plan, "s"), (True, ""))
        done = fixture_text("legacy-running").replace("- [ ] T", "- [x] T")
        plan = self.load("legacy-running", done)
        self.assertEqual(guards.decide_stop(plan, "s"), (True, ""))
        self.assertEqual(guards.decide_stop(None, "s"), (True, ""))


def running(text: str) -> str:
    return replace_once(text, "status: planning", "status: running")


class TierStopTest(StopTestBase):
    def test_ready_node_continues(self) -> None:
        plan = self.load("team-ok", running(fixture_text("team-ok")))
        decision = guards.evaluate_stop(plan, "a")
        self.assertEqual((decision.allow, decision.next, decision.stalls), (False, "N1", 0))
        self.assertIn("N1", decision.reason)
        self.assertIn("owner: implementer", decision.reason)

    def test_only_nodes_behind_a_blocked_node_release(self) -> None:
        text = running(fixture_text("team-ok"))
        text = replace_once(text, "- [ ] N1 ", "- [!] N1 ")
        text = replace_once(text, "- [ ] N2 ", "- [x] N2 ")
        decision = guards.evaluate_stop(self.load("team-ok", text), "b")
        self.assertTrue(decision.allow)
        self.assertIsNone(decision.next)
        self.assertIn("N1", decision.reason)

    def test_not_run_scenarios_keep_the_run_going(self) -> None:
        text = running(fixture_text("base-ok")).replace("- [ ] T", "- [x] T")
        decision = guards.evaluate_stop(self.load("base-ok", text), "c")
        self.assertEqual((decision.allow, decision.next), (False, None))
        self.assertIn("AT-01, AT-02, AT-03", decision.reason)
        passed = text.replace("| NOT_RUN |", "| PASS |")
        self.assertTrue(guards.evaluate_stop(self.load("base-ok", passed), "d").allow)

    def test_failed_scenarios_do_not_block_the_stop(self) -> None:
        text = running(fixture_text("base-ok")).replace("- [ ] T", "- [x] T").replace("| NOT_RUN |", "| FAIL |")
        self.assertTrue(guards.evaluate_stop(self.load("base-ok", text), "f").allow)

    def test_only_blocked_nodes_left_release(self) -> None:
        text = running(fixture_text("base-ok"))
        text = replace_once(text, "- [ ] T1 ", "- [x] T1 ")
        text = replace_once(text, "- [ ] T2 ", "- [!] T2 ")
        self.assertTrue(guards.evaluate_stop(self.load("base-ok", text), "g").allow)

    def test_stall_limit_from_environment(self) -> None:
        plan = self.load("team-ok", running(fixture_text("team-ok")))
        with mock.patch.dict(os.environ, {"PLAN_LOOP_MAX_STALLS": "3"}):
            results = [guards.evaluate_stop(plan, "e") for _ in range(5)]
        self.assertEqual([r.allow for r in results], [False, False, False, True, False])
        self.assertEqual([r.stalls for r in results], [0, 1, 2, 3, 1])

    def test_default_limit_is_five(self) -> None:
        plan = self.load("team-ok", running(fixture_text("team-ok")))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLAN_LOOP_MAX_STALLS", None)
            results = [guards.evaluate_stop(plan, "h").allow for _ in range(6)]
        self.assertEqual(results, [False] * 5 + [True])

    def test_progress_resets_the_stall_count(self) -> None:
        text = running(fixture_text("team-ok"))
        plan = self.load("team-ok", text)
        self.assertEqual([guards.evaluate_stop(plan, "p", max_stalls=3).stalls for _ in range(3)], [0, 1, 2])
        plan = self.load("team-ok", replace_once(text, "- [ ] N1 ", "- [x] N1 "))
        decision = guards.evaluate_stop(plan, "p", max_stalls=3)
        self.assertEqual((decision.allow, decision.stalls, decision.next), (False, 0, "N2"))
        recorded = replace_once(text, "| AT-01 | NOT_RUN |", "| AT-01 | FAIL |")
        recorded = replace_once(recorded, "- [ ] N1 ", "- [x] N1 ")
        decision = guards.evaluate_stop(self.load("team-ok", recorded), "p", max_stalls=3)
        self.assertEqual(decision.stalls, 0)

    def test_not_running_allows(self) -> None:
        plan = self.load("team-ok", fixture_text("team-ok"))
        self.assertEqual(guards.decide_stop(plan, "x"), (True, ""))


if __name__ == "__main__":
    unittest.main()
