"""Codex hooks on planlib: byte-for-byte compatibility with commit 7aa60fc on legacy plans,
the same decisions on tier plans, and fail-open when planlib cannot be imported.

Every hook runs as a subprocess with a Codex-shaped event on stdin, as Codex runs it.
The baseline hooks are read from git (``git show 7aa60fc:codex/plan-loop/hooks/<file>``).
Fixtures under tests/plan-loop/fixtures are only read; each test copies one into a
temporary repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HOOKS = REPO / "codex" / "plan-loop" / "hooks"
CLI = REPO / "skills" / "plan-loop" / "scripts" / "plan_loop.py"
FIXTURES = REPO / "tests" / "plan-loop" / "fixtures"
BASE = "7aa60fc"
HOOK_FILES = ("plan_state.py", "plan_guard.py", "stop_guard.py")

EMPTY = b"{}\n"
PREFIX = "plan-loop: {name} is still in planning (read-only outside plan/)."
SHELL_REASON = PREFIX + " This shell command looks mutating. Use read-only commands until the plan is approved."
PATCH_REASON = PREFIX + " Blocked edit to: {targets}. Finish the plan and get approval first."
PATCH_ADD = "*** Begin Patch\n*** Add File: src/a.txt\n+hi\n*** End Patch"
# Imports plan_state from the hook directory in argv[1] and prints what the hooks read.
SHIM_PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import plan_state as s
p = s.find_active_plan(sys.argv[2])
q = s.parse_plan(p.root, p.path)
same = (q.status, q.open_tasks, q.done_count) == (p.status, p.open_tasks, p.done_count)
print(json.dumps([isinstance(p, s.ActivePlan), p.status, p.open_tasks, p.done_count, str(p.root), str(p.path),
                  same, callable(s.read_event), callable(s.emit)]))
"""

_old_hooks: Dict[str, Path] = {}


def old_hooks() -> Path:
    """The three hooks as they were at BASE, extracted once per test run."""
    if "dir" not in _old_hooks:
        target = Path(tempfile.mkdtemp(prefix="plan-loop-old-hooks-")).resolve()
        unittest.addModuleCleanup(shutil.rmtree, target, True)
        for name in HOOK_FILES:
            result = subprocess.run(
                ["git", "-C", str(REPO), "show", f"{BASE}:codex/plan-loop/hooks/{name}"],
                capture_output=True,
            )
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", "replace").strip()
                raise RuntimeError(f"cannot read {name} at {BASE} from git: {detail}")
            (target / name).write_bytes(result.stdout)
        _old_hooks["dir"] = target
    return _old_hooks["dir"]


def shell(cwd: Path, command: object) -> dict:
    return {"cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": command}}


def patch(cwd: Path, body: str) -> dict:
    return {"cwd": str(cwd), "tool_name": "apply_patch", "tool_input": {"command": body}}


def stop(cwd: Path, session: str) -> dict:
    return {"cwd": str(cwd), "session_id": session}


class HookTestCase(unittest.TestCase):
    """A temporary repository <tmp>/r with .git and plan/, and an isolated TMPDIR for stall state."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="plan-loop-hooks-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "r"
        (self.root / "plan").mkdir(parents=True)
        (self.root / ".git").mkdir()
        self.state_tmp = self.tmp / "tmpdir"
        self.state_tmp.mkdir()

    # --- repository -------------------------------------------------------

    @property
    def plan_path(self) -> Path:
        slug = (self.root / "plan" / "ACTIVE").read_text(encoding="utf-8").strip()
        return self.root / "plan" / f"{slug}.md"

    def use(self, slug: str, active: bool = True) -> Path:
        """Copy a fixture into the repository and, by default, make it the active plan."""
        path = self.root / "plan" / f"{slug}.md"
        shutil.copyfile(FIXTURES / f"{slug}.md", path)
        if active:
            (self.root / "plan" / "ACTIVE").write_text(slug + "\n", encoding="utf-8")
        return path

    def edit_plan(self, old: str, new: str) -> None:
        text = self.plan_path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        self.plan_path.write_text(text.replace(old, new), encoding="utf-8")

    def cli(self, *args: str) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "--cwd", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(),
        )
        self.assertEqual(result.returncode, 0, f"plan_loop.py {' '.join(args)}\n{result.stdout}{result.stderr}")

    # --- running hooks ----------------------------------------------------

    def env(self, tmpdir: Optional[Path] = None, **extra: str) -> Dict[str, str]:
        environment = dict(os.environ)
        for name in ("PYTHONPATH", "PLAN_LOOP_MAX_STALLS"):
            environment.pop(name, None)
        environment["TMPDIR"] = str(tmpdir or self.state_tmp)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment.update(extra)
        return environment

    def run_hook(
        self,
        hook: Path,
        event: object,
        env: Optional[Dict[str, str]] = None,
        flags: Sequence[str] = (),
        raw: Optional[bytes] = None,
    ) -> subprocess.CompletedProcess:
        stdin = raw if raw is not None else json.dumps(event).encode("utf-8")
        return subprocess.run(
            [sys.executable, *flags, str(hook)],
            input=stdin,
            capture_output=True,
            cwd=str(self.tmp),
            env=env if env is not None else self.env(),
        )

    def hook(self, name: str, event: object, env: Optional[Dict[str, str]] = None, **kwargs) -> bytes:
        """Run the current hook; it must exit 0 with nothing on stderr. Returns stdout."""
        result = self.run_hook(HOOKS / name, event, env, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stderr, b"")
        return result.stdout

    def denial(self, output: bytes) -> str:
        data = json.loads(output)
        self.assertEqual(set(data), {"hookSpecificOutput"})
        specific = data["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertEqual(specific["permissionDecision"], "deny")
        return specific["permissionDecisionReason"]

    def assertBlocks(self, output: bytes) -> str:
        data = json.loads(output)
        self.assertEqual(set(data), {"decision", "reason"})
        self.assertEqual(data["decision"], "block")
        return data["reason"]


class CompareTestCase(HookTestCase):
    """Runs the hook at BASE and the current hook on the same event and compares stdout bytes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.old = old_hooks()

    def same_output(
        self,
        name: str,
        event: object,
        old_env: Optional[Dict[str, str]] = None,
        new_env: Optional[Dict[str, str]] = None,
        raw: Optional[bytes] = None,
    ) -> bytes:
        before = self.run_hook(self.old / name, event, old_env, raw=raw)
        self.assertEqual(before.returncode, 0, before.stderr.decode("utf-8", "replace"))
        after = self.hook(name, event, new_env, raw=raw)
        self.assertEqual(after, before.stdout)
        return after


class LegacyGuardTest(CompareTestCase):
    """AT-12 steps 2 and 3: plan_guard.py on a legacy plan in planning."""

    def setUp(self) -> None:
        super().setUp()
        self.use("legacy-planning")
        self.plan_name = "legacy-planning.md"

    def test_patch_outside_plan_is_denied_as_before(self) -> None:
        output = self.same_output("plan_guard.py", patch(self.root, PATCH_ADD))
        self.assertIn(b'"permissionDecision": "deny"', output)
        self.assertIn(b"src/a.txt", output)
        self.assertEqual(self.denial(output), PATCH_REASON.format(name=self.plan_name, targets="src/a.txt"))

    def test_mutating_shell_is_denied_and_read_only_shell_allowed(self) -> None:
        denied = self.same_output("plan_guard.py", shell(self.root, "rm -rf src"))
        self.assertEqual(self.denial(denied), SHELL_REASON.format(name=self.plan_name))
        self.assertEqual(self.same_output("plan_guard.py", shell(self.root, "ls -la")), EMPTY)

    def test_shell_commands_match(self) -> None:
        commands = [
            "rm -rf src",
            "ls -la",
            "git status",
            "git commit -m wip",
            "sed -i s/a/b/ src/settings.py",
            "pip install requests",
            "echo hi > out.txt",
            "echo hi > plan/notes.md",
            "echo hi >> plan/notes.md",
            "cat src/settings.py 2>/dev/null",
            "cat src/settings.py > /dev/null",
            "python3 -c 'print(1)' | tee log.txt",
            f"echo hi > {self.root}/plan/notes.md",
            ["bash", "-lc", "rm -rf src"],
            "",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.same_output("plan_guard.py", shell(self.root, command))

    def test_patches_match(self) -> None:
        bodies = [
            PATCH_ADD,
            "*** Begin Patch\n*** Update File: plan/legacy-planning.md\n@@\n+x\n*** End Patch",
            "*** Begin Patch\n*** Add File: plan/notes.md\n+x\n*** End Patch",
            "*** Begin Patch\n*** Update File: plan/notes.md\n*** Move to: src/notes.md\n@@\n+x\n*** End Patch",
            "*** Begin Patch\n*** Delete File: src/settings.py\n*** Add File: docs/a.md\n+x\n*** End Patch",
            f"*** Begin Patch\n*** Add File: {self.root}/plan/abs.md\n+x\n*** End Patch",
            "*** Begin Patch\n*** Add File: plan/../src/escape.txt\n+x\n*** End Patch",
            "no patch markers at all",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.same_output("plan_guard.py", patch(self.root, body))

    def test_other_tools_and_odd_events_match(self) -> None:
        events = [
            {"cwd": str(self.root), "tool_name": "Read", "tool_input": {"command": "rm -rf src"}},
            {"cwd": str(self.root), "tool_name": "Bash"},
            {"cwd": str(self.root), "tool_name": "Bash", "tool_input": {}},
            {"cwd": str(self.root / "plan"), "tool_name": "Bash", "tool_input": {"command": "rm x"}},
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf src"}},
            {},
        ]
        for event in events:
            with self.subTest(event=event):
                self.same_output("plan_guard.py", event)
        for raw in (b"", b"not json"):
            with self.subTest(raw=raw):
                self.assertEqual(self.same_output("plan_guard.py", None, raw=raw), EMPTY)

    def test_planning_plan_does_not_hold_the_stop(self) -> None:
        self.assertEqual(self.same_output("stop_guard.py", stop(self.root, "legacy-planning")), EMPTY)

    def test_isolated_python_runs_the_hook(self) -> None:
        """python3 -S -I does not add the script directory; the hook adds it itself."""
        event = shell(self.root, "rm -rf src")
        isolated = self.hook("plan_guard.py", event, flags=("-S", "-I", "-B"))
        self.assertEqual(isolated, self.hook("plan_guard.py", event))


class ShimTest(CompareTestCase):
    """plan_state.py keeps ActivePlan, find_active_plan, parse_plan, read_event and emit."""

    def probe(self, hooks: Path) -> list:
        result = subprocess.run(
            [sys.executable, "-c", SHIM_PROBE, str(hooks), str(self.root)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.tmp),
            env=self.env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_names_and_counts_match_the_old_shim(self) -> None:
        nodes = [
            "N1 CSV parser with header validation",
            "N2 Order repository bulk insert",
            "N3 Import endpoint",
            "G1 Execute all mandatory scenarios on the frozen candidate",
            "G2 Independent review of diff and evidence",
        ]
        for slug in ("legacy-planning", "legacy-running", "team-ok"):
            with self.subTest(slug=slug):
                self.use(slug)
                new = self.probe(HOOKS)
                self.assertEqual(new, self.probe(self.old))
                self.assertEqual([new[0], *new[6:]], [True, True, True, True])
                self.assertEqual(new[4:6], [str(self.root), str(self.root / "plan" / f"{slug}.md")])
                if slug == "team-ok":
                    self.assertEqual(new[1:4], ["planning", nodes, 0])


class LegacyStopTest(CompareTestCase):
    """AT-12 step 4 and the stall rule: stop_guard.py on a legacy plan that is running."""

    def setUp(self) -> None:
        super().setUp()
        self.use("legacy-running")
        self.old_tmp = self.tmp / "old-tmpdir"
        self.old_tmp.mkdir()

    def stop_both(self, session: str, **extra: str) -> bytes:
        return self.same_output(
            "stop_guard.py",
            stop(self.root, session),
            old_env=self.env(self.old_tmp, **extra),
            new_env=self.env(self.state_tmp, **extra),
        )

    def assertSameStallState(self, session: str) -> None:
        old = (self.old_tmp / "plan-loop-stop" / f"{session}.json").read_bytes()
        new = (self.state_tmp / "plan-loop-stop" / f"{session}.json").read_bytes()
        self.assertEqual(new, old)

    def test_open_tasks_block_the_stop_as_before(self) -> None:
        output = self.stop_both("at12")
        self.assertIn(b'"decision": "block"', output)
        self.assertIn(b"2 open task(s)", output)
        self.assertNotIn(b"T3", output)  # a [!] task is not open
        self.assertSameStallState("at12")

    def test_stall_sequence_matches(self) -> None:
        blocked = []
        for step in range(6):
            if step == 3:
                self.edit_plan("- [ ] T2 ", "- [x] T2 ")
            with self.subTest(step=step):
                output = self.stop_both("stall", PLAN_LOOP_MAX_STALLS="2")
                blocked.append(output != EMPTY)
                self.assertSameStallState("stall")
        # Two continuations without progress, then the stop is allowed; ticking T2 is progress.
        self.assertEqual(blocked, [True, True, False, True, True, False])

    def test_nothing_open_allows_the_stop(self) -> None:
        self.edit_plan("- [ ] T2 ", "- [x] T2 ")
        self.edit_plan("- [ ] T4 ", "- [x] T4 ")
        self.assertEqual(self.stop_both("done"), EMPTY)

    def test_running_plan_does_not_restrict_tools(self) -> None:
        self.assertEqual(self.same_output("plan_guard.py", shell(self.root, "rm -rf src")), EMPTY)
        self.assertEqual(self.same_output("plan_guard.py", patch(self.root, PATCH_ADD)), EMPTY)


class NoActivePlanTest(CompareTestCase):
    """Without an active plan neither hook does anything, as before."""

    def test_no_marker(self) -> None:
        self.use("legacy-planning", active=False)
        self.assertEqual(self.same_output("plan_guard.py", shell(self.root, "rm -rf src")), EMPTY)
        self.assertEqual(self.same_output("plan_guard.py", patch(self.root, PATCH_ADD)), EMPTY)
        self.assertEqual(self.same_output("stop_guard.py", stop(self.root, "none")), EMPTY)

    def test_marker_names_a_missing_plan(self) -> None:
        (self.root / "plan" / "ACTIVE").write_text("missing\n", encoding="utf-8")
        self.assertEqual(self.same_output("plan_guard.py", shell(self.root, "rm -rf src")), EMPTY)
        self.assertEqual(self.same_output("stop_guard.py", stop(self.root, "missing")), EMPTY)

    def test_search_stops_at_the_git_root(self) -> None:
        outer = self.tmp / "outer"
        (outer / "plan").mkdir(parents=True)
        shutil.copyfile(FIXTURES / "legacy-planning.md", outer / "plan" / "legacy-planning.md")
        (outer / "plan" / "ACTIVE").write_text("legacy-planning\n", encoding="utf-8")
        inner = outer / "inner"
        (inner / ".git").mkdir(parents=True)
        self.assertEqual(self.same_output("plan_guard.py", shell(inner, "rm -rf src")), EMPTY)

    def test_no_cwd(self) -> None:
        self.use("legacy-running")
        self.assertEqual(self.same_output("plan_guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm x"}}), EMPTY)
        self.assertEqual(self.same_output("stop_guard.py", {"session_id": "no-cwd"}), EMPTY)


class TierHookTest(HookTestCase):
    """AT-22: the hooks on a team plan (tests/plan-loop/fixtures/team-ok.md)."""

    def setUp(self) -> None:
        super().setUp()
        self.use("team-ok")
        self.plan_name = "team-ok.md"

    def run_plan(self) -> None:
        self.cli("advance", "approved")
        self.cli("advance", "running")

    def test_planning_patch_outside_plan_is_denied(self) -> None:
        reason = self.denial(self.hook("plan_guard.py", patch(self.root, PATCH_ADD)))
        self.assertIn("src/a.txt", reason)
        self.assertEqual(reason, PATCH_REASON.format(name=self.plan_name, targets="src/a.txt"))

    def test_planning_patch_inside_plan_is_allowed(self) -> None:
        body = "*** Begin Patch\n*** Update File: plan/team-ok.md\n@@\n+x\n*** End Patch"
        self.assertEqual(self.hook("plan_guard.py", patch(self.root, body)), EMPTY)

    def test_planning_shell(self) -> None:
        reason = self.denial(self.hook("plan_guard.py", shell(self.root, "rm -rf src")))
        self.assertEqual(reason, SHELL_REASON.format(name=self.plan_name))
        self.assertEqual(self.hook("plan_guard.py", shell(self.root, "ls -la")), EMPTY)
        self.assertEqual(self.hook("plan_guard.py", shell(self.root, "echo note > plan/notes.md")), EMPTY)

    def test_planning_plan_does_not_hold_the_stop(self) -> None:
        self.assertEqual(self.hook("stop_guard.py", stop(self.root, "at22-planning")), EMPTY)

    def test_running_blocks_on_a_ready_node_and_releases_behind_a_blocked_node(self) -> None:
        self.run_plan()
        reason = self.assertBlocks(self.hook("stop_guard.py", stop(self.root, "at22-a")))
        self.assertIn("N1", reason)
        self.assertEqual(self.hook("plan_guard.py", shell(self.root, "rm -rf src")), EMPTY)
        self.assertEqual(self.hook("plan_guard.py", patch(self.root, PATCH_ADD)), EMPTY)
        self.cli("node", "block", "N1", "--reason", "no access")
        self.cli("node", "done", "N2")
        self.assertEqual(self.hook("stop_guard.py", stop(self.root, "at22-b")), EMPTY)

    def test_stall_limit_releases_the_stop(self) -> None:
        self.run_plan()
        env = self.env(PLAN_LOOP_MAX_STALLS="3")
        outputs = [self.hook("stop_guard.py", stop(self.root, "at22-stall"), env) for _ in range(4)]
        for output in outputs[:3]:
            self.assertIn("N1", self.assertBlocks(output))
        self.assertEqual(outputs[3], EMPTY)


class FailOpenTest(HookTestCase):
    """When planlib cannot be imported the hooks print {} and exit 0 with one stderr line."""

    BROKEN = {
        "missing": None,
        "import-error": 'raise ImportError("planlib disabled for this test")\n',
        "syntax-error": "def broken(:\n",
    }

    def checkout(self, variant: str) -> Path:
        """A copy of the current hooks whose skill tree is missing or holds a broken planlib."""
        tree = self.tmp / f"checkout-{variant}"
        hooks = tree / "codex" / "plan-loop" / "hooks"
        hooks.mkdir(parents=True)
        for name in HOOK_FILES:
            shutil.copyfile(HOOKS / name, hooks / name)
        source = self.BROKEN[variant]
        if source is not None:
            package = tree / "skills" / "plan-loop" / "scripts" / "planlib"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(source, encoding="utf-8")
        return hooks

    def assertFailsOpen(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, EMPTY)
        message = result.stderr.decode("utf-8")
        self.assertTrue(message.endswith("\n"))
        self.assertEqual(message.count("\n"), 1, message)
        self.assertTrue(message.startswith("plan-loop: "), message)
        self.assertIn("planlib", message)

    def test_guard_fails_open(self) -> None:
        self.use("legacy-planning")
        self.denial(self.hook("plan_guard.py", shell(self.root, "rm -rf src")))  # denied with planlib
        for variant in self.BROKEN:
            with self.subTest(variant=variant):
                hooks = self.checkout(variant)
                self.assertFailsOpen(self.run_hook(hooks / "plan_guard.py", shell(self.root, "rm -rf src")))
                self.assertFailsOpen(self.run_hook(hooks / "plan_guard.py", patch(self.root, PATCH_ADD)))

    def test_stop_fails_open(self) -> None:
        self.use("legacy-running")
        self.assertBlocks(self.hook("stop_guard.py", stop(self.root, "with-planlib")))
        for variant in self.BROKEN:
            with self.subTest(variant=variant):
                hooks = self.checkout(variant)
                self.assertFailsOpen(self.run_hook(hooks / "stop_guard.py", stop(self.root, f"fail-{variant}")))
        for variant in self.BROKEN:
            self.assertFalse((self.state_tmp / "plan-loop-stop" / f"fail-{variant}.json").exists())


class InstallerTest(HookTestCase):
    """AT-13: codex/plan-loop/install.py is unchanged and still installs the same hook paths."""

    def install(self, *args: str) -> str:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO / "codex" / "plan-loop" / "install.py"),
                "--hooks-file",
                str(self.tmp / "hooks.json"),
                "--skills-dir",
                str(self.tmp / "skills"),
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.tmp),
            env=self.env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def backups(self) -> list:
        return sorted(path.name for path in self.tmp.iterdir() if path.name.startswith("hooks.json.bak-"))

    def test_install_is_unchanged(self) -> None:
        result = subprocess.run(
            ["git", "-C", str(REPO), "diff", "--stat", BASE, "--", "codex/plan-loop/install.py"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_dry_run_apply_and_rerun(self) -> None:
        hooks_file = self.tmp / "hooks.json"
        original = '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo keep"}]}]}}\n'
        hooks_file.write_text(original, encoding="utf-8")

        self.install()
        self.assertEqual(hooks_file.read_text(encoding="utf-8"), original)
        self.assertFalse((self.tmp / "skills").exists())
        self.assertEqual(self.backups(), [])

        self.install("--apply")
        self.assertEqual(os.readlink(self.tmp / "skills" / "plan-loop"), str(REPO / "skills" / "plan-loop"))
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        stop_groups, tool_groups = data["hooks"]["Stop"], data["hooks"]["PreToolUse"]
        self.assertEqual((len(stop_groups), len(tool_groups)), (2, 1))
        self.assertEqual(stop_groups[0]["hooks"][0]["command"], "echo keep")
        self.assertTrue(stop_groups[1]["hooks"][0]["command"].endswith(f'"{HOOKS / "stop_guard.py"}"'))
        self.assertTrue(tool_groups[0]["hooks"][0]["command"].endswith(f'"{HOOKS / "plan_guard.py"}"'))
        self.assertTrue((HOOKS / "stop_guard.py").is_file() and (HOOKS / "plan_guard.py").is_file())
        self.assertEqual(len(self.backups()), 1)

        installed = hooks_file.read_bytes()
        self.assertIn("already", self.install("--apply"))
        self.assertEqual(hooks_file.read_bytes(), installed)
        self.assertEqual(len(self.backups()), 1)


if __name__ == "__main__":
    unittest.main()
