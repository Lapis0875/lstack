"""Shared helpers for the plan-loop unit tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / "skills" / "plan-loop" / "scripts"
CLI = SCRIPTS / "plan_loop.py"
FIXTURES = HERE / "fixtures"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from planlib import checks, planfile  # noqa: E402


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.md").read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise AssertionError(f"fixture text does not contain {old!r}")
    return text.replace(old, new, 1)


class TempRepo:
    """A temporary repository: <root>/.git, <root>/plan/<slug>.md and plan/ACTIVE."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name).resolve()
        self.root = self.base / "r"
        (self.root / "plan").mkdir(parents=True)
        (self.root / ".git").mkdir()

    def close(self) -> None:
        self._dir.cleanup()

    def write_plan(self, slug: str, text: str, active: bool = True, raw: Optional[bytes] = None) -> Path:
        path = self.root / "plan" / f"{slug}.md"
        path.write_bytes(raw if raw is not None else text.encode("utf-8"))
        if active:
            (self.root / "plan" / "ACTIVE").write_text(slug + "\n", encoding="utf-8")
        return path

    def parse(self, slug: str, text: str, raw: Optional[bytes] = None) -> planfile.Plan:
        path = self.write_plan(slug, text, active=False, raw=raw)
        return planfile.parse_plan(self.root, path)


def codes(findings: Iterable[checks.Finding], severity: Optional[str] = None) -> Set[str]:
    return {f.code for f in findings if severity is None or f.severity == severity}


def run_cli(*args: str, env: Optional[Dict[str, str]] = None, cwd: Optional[Path] = None, python_flags=()):
    environment = dict(os.environ)
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, *python_flags, str(CLI), *args],
        cwd=str(cwd or REPO),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
