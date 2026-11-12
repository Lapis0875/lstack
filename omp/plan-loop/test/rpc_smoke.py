#!/usr/bin/env python3
"""Run `/plan-loop status` in a real omp RPC process without any model call (AT-16).

Safety: the prompt is sent only after omp lists the extension's `plan-loop`
command, and the process is killed the moment an `agent_start` frame appears.

Exit codes: 0 ok, 1 completed but not ok, 3 command never listed (no prompt
sent), 4 an agent turn started, 5 the prompt did not complete in time.
The prompt completes through the `response` with the same id when that carries
`data.agentInvoked: false` (omp's local completion), else through its `prompt_result`.
Prints one JSON line: {"ok", "notify", "notifyType", "agentInvoked", "status", "ompExit",
"completedBy"}, where completedBy is "response", "prompt_result" or null.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "skills" / "plan-loop" / "scripts" / "plan_loop.py"
PROMPT_ID = "1"
PROMPT = {"id": PROMPT_ID, "type": "prompt", "message": "/plan-loop status"}
COMMAND_TIMEOUT = 20.0
RESULT_TIMEOUT = 20.0
EXIT_WAIT = 10.0

EXIT_OK = 0
EXIT_NOT_OK = 1
EXIT_NO_COMMAND = 3
EXIT_AGENT_STARTED = 4
EXIT_NO_RESULT = 5

TIMEOUT = object()
EOF = object()


def omp_argv(cwd: str, ext: str) -> List[str]:
    return [
        "omp", "--mode", "rpc", "--no-session", "--no-extensions", "--no-skills", "--no-rules",
        "--no-context-files", "--no-title", "--no-lsp", "--no-tools", "--cwd", cwd, "-e", ext,
    ]


def lists_plan_loop(value: Any) -> bool:
    """True when some object below value is {"name": "plan-loop", "source": "extension", ...}."""
    if isinstance(value, dict):
        if value.get("name") == "plan-loop" and value.get("source") == "extension":
            return True
        return any(lists_plan_loop(item) for item in value.values())
    if isinstance(value, list):
        return any(lists_plan_loop(item) for item in value)
    return False


class Omp:
    """An omp RPC process whose stdout frames arrive on a queue."""

    def __init__(self, argv: List[str], env: Dict[str, str]) -> None:
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.frames: "queue.Queue[Any]" = queue.Queue()
        self.stderr: Deque[str] = deque(maxlen=40)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in iter(self.proc.stdout.readline, b""):
            try:
                frame = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if isinstance(frame, dict):
                self.frames.put(frame)
        self.frames.put(EOF)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in iter(self.proc.stderr.readline, b""):
            self.stderr.append(raw.decode("utf-8", errors="replace").rstrip("\n"))

    def next_frame(self, deadline: float) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return TIMEOUT
        try:
            return self.frames.get(timeout=remaining)
        except queue.Empty:
            return TIMEOUT

    def send(self, frame: Dict[str, Any]) -> bool:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
            return True
        except OSError:
            return False

    def close_stdin(self) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def kill(self) -> int:
        if self.proc.poll() is None:
            self.proc.kill()
        return self.proc.wait()


class Run:
    def __init__(self) -> None:
        self.notices: List[Dict[str, Any]] = []
        self.agent_invoked: Optional[bool] = None
        self.status: Optional[str] = None
        self.omp_exit: Optional[int] = None
        self.completed_by: Optional[str] = None

    def report(self) -> Dict[str, Any]:
        first = self.notices[0] if self.notices else {}
        ok = (
            self.agent_invoked is False
            and self.status == "completed"
            and bool(self.notices)
            and self.omp_exit == 0
        )
        return {
            "ok": ok,
            "notify": first.get("message"),
            "notifyType": first.get("notifyType"),
            "agentInvoked": self.agent_invoked,
            "status": self.status,
            "ompExit": self.omp_exit,
            "completedBy": self.completed_by,
        }


def finish(run: Run, omp: Omp, code: int, problem: Optional[str] = None) -> int:
    if problem is not None:
        run.omp_exit = omp.kill()
        print(f"rpc_smoke: {problem}", file=sys.stderr)
        for line in omp.stderr:
            print(f"omp: {line}", file=sys.stderr)
    for extra in run.notices[1:]:
        print(f"rpc_smoke: extra notify: {extra.get('message')!r} ({extra.get('notifyType')})", file=sys.stderr)
    report = run.report()
    print(json.dumps(report, ensure_ascii=False))
    if problem is None and not report["ok"]:
        return EXIT_NOT_OK
    return code


def drive(cwd: str, ext: str) -> int:
    env = dict(os.environ)
    env["PLAN_LOOP_CLI"] = str(CLI)
    omp = Omp(omp_argv(cwd, ext), env)
    run = Run()

    # 1. Wait for the extension command; send nothing before it is listed.
    deadline = time.monotonic() + COMMAND_TIMEOUT
    while True:
        frame = omp.next_frame(deadline)
        if frame is TIMEOUT or frame is EOF:
            return finish(run, omp, EXIT_NO_COMMAND, "plan-loop was not listed by available_commands_update; no prompt sent")
        kind = frame.get("type")
        if kind == "agent_start":
            return finish(run, omp, EXIT_AGENT_STARTED, "agent_start before any prompt")
        if kind == "extension_error":
            print(f"rpc_smoke: extension_error: {json.dumps(frame, ensure_ascii=False)}", file=sys.stderr)
        if kind == "available_commands_update" and lists_plan_loop(frame):
            break

    # 2. Send the command and wait for it to complete; any agent turn is a failure.
    if not omp.send(PROMPT):
        return finish(run, omp, EXIT_NO_RESULT, "omp closed stdin before the prompt")
    deadline = time.monotonic() + RESULT_TIMEOUT
    while run.status is None:
        frame = omp.next_frame(deadline)
        if frame is TIMEOUT or frame is EOF:
            return finish(run, omp, EXIT_NO_RESULT, f"prompt {PROMPT_ID} did not complete (no local response or prompt_result)")
        kind = frame.get("type")
        if kind == "agent_start":
            return finish(run, omp, EXIT_AGENT_STARTED, "agent_start after /plan-loop status")
        if kind == "extension_ui_request" and frame.get("method") == "notify":
            run.notices.append(frame)
        elif kind == "prompt_result" and frame.get("id") == PROMPT_ID:
            run.agent_invoked = frame.get("agentInvoked")
            run.status = frame.get("status")
            run.completed_by = "prompt_result"
        elif kind == "response" and frame.get("id") == PROMPT_ID:
            data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
            if frame.get("success") is True and data.get("agentInvoked") is False:
                # Completed locally; omp sends no prompt_result for this case.
                run.agent_invoked = False
                run.status = "completed"
                run.completed_by = "response"
            elif frame.get("success") is False:
                print(f"rpc_smoke: prompt failed: {frame.get('error')}", file=sys.stderr)

    # 3. Close stdin and let omp exit on its own; keep watching for agent turns.
    omp.close_stdin()
    deadline = time.monotonic() + EXIT_WAIT
    while True:
        frame = omp.next_frame(deadline)
        if frame is TIMEOUT:
            return finish(run, omp, EXIT_NOT_OK, f"omp did not exit within {EXIT_WAIT:.0f}s after stdin closed")
        if frame is EOF:
            break
        if frame.get("type") == "agent_start":
            return finish(run, omp, EXIT_AGENT_STARTED, "agent_start after the prompt completed")
    try:
        run.omp_exit = omp.proc.wait(timeout=max(deadline - time.monotonic(), 0.1))
    except subprocess.TimeoutExpired:
        return finish(run, omp, EXIT_NOT_OK, "omp closed stdout but did not exit")
    return finish(run, omp, EXIT_OK)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cwd", required=True, help="repository whose plan/ACTIVE omp should see")
    parser.add_argument("--ext", required=True, help="extension directory to load with -e")
    args = parser.parse_args(argv)
    return drive(args.cwd, args.ext)


if __name__ == "__main__":
    sys.exit(main())
