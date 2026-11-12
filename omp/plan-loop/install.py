#!/usr/bin/env python3
"""Link the plan-loop omp extension and skill into an omp agent directory.

Default is a dry run: prints what would change and touches nothing. `--apply`
creates the links:
  1. <extensions-dir>/plan-loop -> <repo>/omp/plan-loop
  2. <skills-dir>/plan-loop     -> <repo>/skills/plan-loop
An entry that already exists is left unchanged; nothing is overwritten or removed.
Restart omp afterwards to load the extension.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
EXTENSION_SRC = HERE
SKILL_SRC = REPO / "skills" / "plan-loop"


def default_agent_dir() -> Path:
    configured = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".omp" / "agent"


def link(kind: str, dst: Path, src: Path, apply: bool) -> bool:
    """Print the planned or made link; return True when a link was (or would be) created."""
    if dst.exists() or dst.is_symlink():
        print(f"{kind}: {dst} already exists, left unchanged")
        return False
    print(f"{kind}: symlink {dst} -> {src}")
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src, target_is_directory=True)
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="create the links (default: dry run)")
    parser.add_argument(
        "--agent-dir",
        type=Path,
        default=None,
        help="root of every write (default: $PI_CODING_AGENT_DIR or ~/.omp/agent)",
    )
    parser.add_argument("--extensions-dir", type=Path, default=None, help="default: <agent-dir>/extensions")
    parser.add_argument("--skills-dir", type=Path, default=None, help="default: <agent-dir>/skills")
    parser.add_argument("--no-skill", action="store_true", help="do not link the skill")
    parser.add_argument("--no-extension", action="store_true", help="do not link the extension")
    args = parser.parse_args(argv)

    agent_dir = args.agent_dir.expanduser() if args.agent_dir else default_agent_dir()
    extensions_dir = args.extensions_dir.expanduser() if args.extensions_dir else agent_dir / "extensions"
    skills_dir = args.skills_dir.expanduser() if args.skills_dir else agent_dir / "skills"

    extension_linked = False
    if not args.no_extension:
        extension_linked = link("extension", extensions_dir / "plan-loop", EXTENSION_SRC, args.apply)
    if not args.no_skill:
        link("skill", skills_dir / "plan-loop", SKILL_SRC, args.apply)

    if not args.apply:
        print("\nDry run. Re-run with --apply to make these changes. Restart omp to load the extension.")
    elif extension_linked:
        print("\nRestart omp to load the extension.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
