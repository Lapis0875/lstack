#!/usr/bin/env python3
"""Install the plan-loop skill and Codex hooks.

Default is a dry run: prints what would change. `--apply` makes the changes:
  1. symlinks skills/plan-loop into ~/.agents/skills/plan-loop (skipped if it exists)
  2. appends the two hook handlers to ~/.codex/hooks.json, after writing a timestamped backup.
Existing hooks are never modified or removed; re-running is idempotent.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SKILL_SRC = REPO / "skills" / "plan-loop"


def handlers(python: str) -> dict[str, dict]:
    hooks = HERE / "hooks"
    return {
        "PreToolUse": {
            "matcher": "^(Bash|apply_patch)$",
            "hooks": [{"type": "command", "command": f'{python} "{hooks / "plan_guard.py"}"', "timeout": 5}],
        },
        "Stop": {
            "hooks": [{"type": "command", "command": f'{python} "{hooks / "stop_guard.py"}"', "timeout": 10}],
        },
    }


def already_installed(groups: list, command: str) -> bool:
    return any(h.get("command") == command for g in groups for h in g.get("hooks", []))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--hooks-file", type=Path, default=Path.home() / ".codex" / "hooks.json")
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".agents" / "skills")
    parser.add_argument("--no-skill", action="store_true", help="only install hooks")
    parser.add_argument("--python", default=shutil.which("python3") or "python3")
    args = parser.parse_args()

    actions: list[str] = []

    link = args.skills_dir / "plan-loop"
    if not args.no_skill:
        if link.exists() or link.is_symlink():
            actions.append(f"skill: {link} already exists, left unchanged")
        else:
            actions.append(f"skill: symlink {link} -> {SKILL_SRC}")
            if args.apply:
                args.skills_dir.mkdir(parents=True, exist_ok=True)
                link.symlink_to(SKILL_SRC, target_is_directory=True)

    data = json.loads(args.hooks_file.read_text(encoding="utf-8")) if args.hooks_file.exists() else {}
    events = data.setdefault("hooks", {})
    added = []
    for event, group in handlers(args.python).items():
        groups = events.setdefault(event, [])
        command = group["hooks"][0]["command"]
        if already_installed(groups, command):
            actions.append(f"hooks: {event} handler already present")
        else:
            groups.append(group)
            added.append(event)
            actions.append(f"hooks: append {event} handler -> {command}")

    if added and args.apply:
        if args.hooks_file.exists():
            backup = args.hooks_file.with_name(f"{args.hooks_file.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(args.hooks_file, backup)
            actions.append(f"hooks: backup written to {backup}")
        args.hooks_file.parent.mkdir(parents=True, exist_ok=True)
        args.hooks_file.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    print("\n".join(actions))
    if not args.apply:
        print("\nDry run. Re-run with --apply to make these changes. Codex asks you to trust new hooks on next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
