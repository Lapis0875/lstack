#!/usr/bin/env python3
"""plan-loop CLI: check, inspect and guard plan files under plan/.

Usage: python3 plan_loop.py [--cwd DIR] [--plan PATH] [--json] <command> ...

Exit codes: 0 success, 1 check errors or an unmet gate, 2 usage or I/O error,
3 state document out of step with the plan, 4 refused transition.
``guard`` and ``stop`` always print the JSON envelope and exit 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from typing import Callable, Dict, List, Optional  # noqa: E402

from planlib import checks, guards, mutate, planfile, state  # noqa: E402
from planlib.checks import Finding  # noqa: E402
from planlib.planfile import Plan  # noqa: E402

EXIT_OK = 0
EXIT_CHECK = 1
EXIT_USAGE = 2
EXIT_DRIFT = 3
EXIT_REFUSED = 4


class UsageError(Exception):
    """Bad command line or request; exit 2."""


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


class Outcome:
    """What a command returns: exit code, findings, envelope data and the text-mode output."""

    def __init__(
        self,
        code: int = EXIT_OK,
        data: Optional[dict] = None,
        findings: Optional[List[Finding]] = None,
        text: Optional[str] = None,
        findings_to_stdout: bool = False,
        error: Optional[str] = None,
    ) -> None:
        self.code = code
        self.data = data if data is not None else {}
        self.findings = findings or []
        self.text = text
        self.findings_to_stdout = findings_to_stdout
        self.error = error  # printed on stderr in text mode


class Context:
    def __init__(self, args: argparse.Namespace) -> None:
        self.cwd = Path(args.cwd) if args.cwd else Path.cwd()
        self.plan_arg: Optional[str] = args.plan
        self.json: bool = args.json
        self.plan: Optional[Plan] = None

    def plan_path_arg(self) -> Optional[Path]:
        if self.plan_arg is None:
            return None
        path = Path(self.plan_arg)
        return path if path.is_absolute() else self.cwd / path

    def load_plan(self, cwd: Optional[str] = None) -> Optional[Plan]:
        """--plan PATH when given, else the active plan found from cwd (default --cwd)."""
        explicit = self.plan_path_arg()
        if explicit is not None:
            if not explicit.is_file():
                raise CliError(f"plan file not found: {explicit}")
            self.plan = planfile.parse_plan(planfile.root_for_plan_path(explicit), explicit)
        else:
            self.plan = planfile.find_active_plan(str(cwd if cwd is not None else self.cwd))
        return self.plan

    def require_plan(self) -> Plan:
        plan = self.load_plan()
        if plan is None:
            raise CliError(f"no active plan (no plan/ACTIVE naming an existing plan above {self.cwd}); pass --plan PATH")
        return plan

    def display_path(self, path: Path) -> str:
        """Relative to the process directory when the file is below it, else absolute."""
        absolute = os.path.abspath(str(path))
        here = os.path.abspath(os.getcwd())
        if absolute.startswith(here.rstrip(os.sep) + os.sep):
            return os.path.relpath(absolute, here)
        return absolute


class Command:
    def __init__(
        self,
        name: str,
        help_text: str,
        configure: Callable[[argparse.ArgumentParser], None],
        run: Callable[[Context, argparse.Namespace], Outcome],
        always_envelope: bool = False,
    ) -> None:
        self.name = name
        self.help = help_text
        self.configure = configure
        self.run = run
        self.always_envelope = always_envelope


COMMANDS: Dict[str, Command] = {}


def register(name: str, help_text: str, always_envelope: bool = False):
    """Decorator for ``run(ctx, args) -> Outcome``; ``run.configure(parser)`` adds arguments."""

    def wrap(run: Callable[[Context, argparse.Namespace], Outcome]):
        configure = getattr(run, "configure", lambda parser: None)
        COMMANDS[name] = Command(name, help_text, configure, run, always_envelope)
        return run

    return wrap


def arguments(configure: Callable[[argparse.ArgumentParser], None]):
    def wrap(run):
        run.configure = configure
        return run

    return wrap


# --------------------------------------------------------------------------- commands


def _phase_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--phase", choices=checks.PHASES, help="default: inferred from the plan status")


@register("check", "parse the plan and run the checks")
@arguments(_phase_arg)
def cmd_check(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    phase = args.phase or checks.infer_phase(plan.status)
    findings = checks.run_checks(plan, phase)
    if phase in ("run", "finish"):
        findings = checks.sort_findings(findings + state.findings(plan))
    errors, warnings = checks.count(findings)
    summary = f"check: {ctx.display_path(plan.path)} phase={phase} errors={errors} warnings={warnings}"
    return Outcome(
        _exit_for(findings),
        data={"phase": phase, "errors": errors, "warnings": warnings},
        findings=findings,
        text=summary,
        findings_to_stdout=True,
    )


def _exit_for(findings: List[Finding]) -> int:
    codes = {finding.code for finding in findings if finding.severity == "error"}
    if codes & {"E-STATE-STALE", "E-STATE-MISSING"}:
        return EXIT_DRIFT
    return EXIT_CHECK if codes else EXIT_OK


@register("status", "summarize the plan: status, nodes, waves, scenarios, drift")
def cmd_status(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.load_plan()
    if plan is None:
        return Outcome(EXIT_OK, data={}, text="plan-loop: no active plan")
    phase = checks.infer_phase(plan.status)
    inspection = state.inspect(plan)
    states = None
    if inspection.doc is not None:
        states = state.node_states(state.sync(plan, inspection.doc, state.now()).doc)
    data = checks.build_status(plan, phase, states=states, state_info=inspection.info())
    findings: List[Finding] = []
    code = EXIT_OK
    if phase in ("run", "finish") and inspection.drift in ("stale", "missing"):
        findings = [f for f in state.findings(plan, inspection) if f.code in ("E-STATE-STALE", "E-STATE-MISSING")]
        code = EXIT_DRIFT
    return Outcome(code, data=data, findings=findings, text=_status_text(ctx, plan, data))


def _status_text(ctx: Context, plan: Plan, data: dict) -> str:
    lines = [f"plan-loop: {plan.slug} ({ctx.display_path(plan.path)})"]
    if plan.legacy:
        lines.append(f"status={plan.status} tier=legacy")
        lines.append(f"tasks: {len(plan.open_tasks)} open, {plan.done_count} done")
        lines.append(f"next: {plan.open_tasks[0] if plan.open_tasks else '-'}")
        return "\n".join(lines)
    lines.append(f"status={plan.status} tier={plan.tier} review={plan.review or '-'} phase={data['phase']}")
    done_requirements = sum(1 for r in data["requirements"] if r["done"])
    lines.append(f"requirements: {done_requirements}/{len(data['requirements'])} checked")
    by_status = {key: 0 for key in ("PASS", "FAIL", "BLOCKED", "NOT_RUN")}
    for scenario in data["scenarios"]:
        by_status[scenario["status"]] = by_status.get(scenario["status"], 0) + 1
    lines.append(
        f"scenarios: {len(data['scenarios'])} — " + ", ".join(f"{key} {value}" for key, value in by_status.items())
    )
    counts = data["counts"]
    lines.append(f"nodes: {len(data['nodes'])} — " + ", ".join(f"{key} {value}" for key, value in counts.items()))
    for wave in data["waves"]:
        lines.append(f"wave {wave['index']} ({wave['state']}): {', '.join(wave['nodes'])}")
    lines.append(f"ready: {', '.join(data['ready']) or '-'}")
    lines.append(f"unreachable: {', '.join(data['unreachable']) or '-'}")
    state = data["state"]
    if state["declared"]:
        lines.append(f"state: {state['path']} exists={'yes' if state['exists'] else 'no'} drift={state['drift']}")
    return "\n".join(lines)


def _digest_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--short", action="store_true", help="print the 12-character form")


@register("digest", "print the review digest of the plan")
@arguments(_digest_args)
def cmd_digest(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    digest = checks.review_digest(plan)
    return Outcome(EXIT_OK, data={"digest": digest, "short": digest[:12]}, text=digest[:12] if args.short else digest)


def _require_team_tier(plan: Plan, command: str) -> None:
    if plan.tier not in planfile.TEAM_TIERS:
        tier = plan.tier or "legacy"
        raise CliError(f"{command} needs a team or workflow plan; this plan is {tier}")


@register("waves", "propose the minimum-depth wave layout")
def cmd_waves(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    _require_team_tier(plan, "waves")
    declared = checks.declared_waves(plan)
    proposed = checks.propose_waves(plan)
    if proposed is None:
        findings = [
            Finding("E-DAG-CYCLE", f"after graph has a cycle through {', '.join(component)}", plan.node(component[0]).line, component[0])
            for component in checks.find_cycles(plan)
        ]
        return Outcome(EXIT_CHECK, data={"waves": [], "declared": declared, "matchesDeclared": False}, findings=findings)
    matches = proposed == declared
    text = [f"Wave {index}: {', '.join(ids)}" for index, ids in enumerate(proposed, start=1)]
    text.append(f"matches declared waves: {'yes' if matches else 'no'}")
    return Outcome(EXIT_OK, data={"waves": proposed, "declared": declared, "matchesDeclared": matches}, text="\n".join(text))


def _brief_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("node", metavar="ID", help="node ID")


@register("brief", "render the delegation brief of a node")
@arguments(_brief_args)
def cmd_brief(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    _require_team_tier(plan, "brief")
    node = plan.node(args.node)
    if node is None:
        raise CliError(f"no node {args.node} in {plan.relpath()}")
    text = checks.render_brief(plan, node)
    return Outcome(EXIT_OK, data={"node": node.id, "text": text}, text=text.rstrip("\n"))


def _request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--request", default="{}", metavar="JSON", help="request object")


def _parse_request(raw: str) -> dict:
    try:
        request = json.loads(raw)
    except ValueError as exc:
        raise UsageError(f"--request is not JSON: {exc}") from None
    if not isinstance(request, dict):
        raise UsageError("--request must be a JSON object")
    return request


@register("guard", "decide whether a tool call may run (always JSON, exit 0)", always_envelope=True)
@arguments(_request_args)
def cmd_guard(ctx: Context, args: argparse.Namespace) -> Outcome:
    try:
        request = _parse_request(args.request)
        cwd = str(request.get("cwd") or ctx.cwd)
        tool = request.get("tool")
        paths = request.get("paths") or []
        if not isinstance(paths, list):
            raise UsageError("paths must be a list of strings")
        label = request.get("label")
        plan = ctx.load_plan(cwd)
        allow, reason = guards.decide_tool(
            plan,
            cwd,
            str(tool) if tool is not None else None,
            command=str(request.get("command") or ""),
            paths=tuple(str(p) for p in paths),
            label=str(label) if label else None,
        )
    except (UsageError, CliError, OSError, UnicodeDecodeError) as exc:
        return Outcome(EXIT_OK, data={"decision": "allow", "reason": f"plan-loop: guard unavailable ({exc})", "status": None})
    status = plan.status if plan is not None else None
    return Outcome(EXIT_OK, data={"decision": "allow" if allow else "deny", "reason": reason, "status": status})


@register("stop", "decide whether the session may stop (always JSON, exit 0)", always_envelope=True)
@arguments(_request_args)
def cmd_stop(ctx: Context, args: argparse.Namespace) -> Outcome:
    try:
        request = _parse_request(args.request)
        cwd = str(request.get("cwd") or ctx.cwd)
        plan = ctx.load_plan(cwd)
        decision = guards.evaluate_stop(plan, request.get("session_id"))
    except (UsageError, CliError, OSError, UnicodeDecodeError) as exc:
        reason = f"plan-loop: stop guard unavailable ({exc})"
        return Outcome(EXIT_OK, data={"decision": "allow", "reason": reason, "next": None, "stalls": 0})
    return Outcome(
        EXIT_OK,
        data={
            "decision": "allow" if decision.allow else "continue",
            "reason": decision.reason,
            "next": decision.next,
            "stalls": decision.stalls,
        },
    )


# --------------------------------------------------------------------------- changes


def _run_change(ctx: Context, build: Callable[[], "mutate.Change"], findings_to_stdout: bool = False) -> Outcome:
    """Build a change, write it, and report it; a refused or failed write leaves the files as they were."""
    try:
        change = build()
        mutate.apply(change)
    except (mutate.Refused, mutate.WriteFailed) as refused:
        return Outcome(
            refused.code,
            data={"error": str(refused)},
            findings=refused.findings,
            findings_to_stdout=findings_to_stdout,
            error=str(refused),
        )
    if change.plan is not None:
        ctx.plan = change.plan
    return Outcome(EXIT_OK, data=change.data, text=change.text)


@register("sync", "create or update the state document from the plan")
def cmd_sync(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    return _run_change(ctx, lambda: mutate.sync(plan, state.now()))


def _advance_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", choices=mutate.PLAN_TRANSITIONS, help="new plan status")
    parser.add_argument("--by", help="who advances the plan (recorded in the state document)")


@register("advance", "check the gate and move the plan status forward")
@arguments(_advance_args)
def cmd_advance(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    return _run_change(ctx, lambda: mutate.advance(plan, args.target, state.now(), args.by or ""), findings_to_stdout=True)


def _node_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=("start", "claim", "done", "fail", "block", "reset"))
    parser.add_argument("node", metavar="ID", help="node ID")
    parser.add_argument("--by", help="who performs or confirms the transition")
    parser.add_argument("--agent", help="claim: agent that did the work")
    parser.add_argument("--provider", help="claim: model provider of that agent")
    parser.add_argument("--model", help="claim: model of that agent")
    parser.add_argument("--effort", help="claim: reasoning effort of that agent")
    parser.add_argument("--evidence", help="claim/done: evidence text")
    parser.add_argument("--reason", help="block (required) and fail: reason")
    parser.add_argument("--cascade", action="store_true", help="reset: also reset every node that depends on it")


@register("node", "move a node through pending, running, claimed, done and blocked")
@arguments(_node_args)
def cmd_node(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    options = mutate.NodeOptions(
        by=args.by,
        agent=args.agent,
        provider=args.provider,
        model=args.model,
        effort=args.effort,
        evidence=args.evidence,
        reason=args.reason,
        cascade=args.cascade,
    )
    return _run_change(ctx, lambda: mutate.node_command(plan, args.action, args.node, options, state.now()))


def _scenario_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=("record",))
    parser.add_argument("scenario", metavar="AT-ID", help="scenario ID")
    parser.add_argument("result", choices=("PASS", "FAIL", "BLOCKED"))
    parser.add_argument("--evidence", required=True, help="observed result and evidence")
    parser.add_argument("--candidate", help="candidate identifier; updates the Candidate: line")
    parser.add_argument("--blocker", help="what blocks the scenario")
    parser.add_argument("--by", help="who records the result")


@register("scenario", "record a scenario result in the execution record")
@arguments(_scenario_args)
def cmd_scenario(ctx: Context, args: argparse.Namespace) -> Outcome:
    plan = ctx.require_plan()
    return _run_change(
        ctx,
        lambda: mutate.record_scenario(
            plan, args.scenario, args.result, args.evidence, state.now(), args.candidate, args.blocker, args.by or ""
        ),
    )


# --------------------------------------------------------------------------- driver


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="plan_loop.py", description="Check, inspect and guard plan-loop plans.")
    parser.add_argument("--cwd", metavar="DIR", help="directory to search upward from for plan/ACTIVE")
    parser.add_argument("--plan", metavar="PATH", help="plan file to use instead of the active plan")
    parser.add_argument("--json", action="store_true", help="print one JSON envelope on stdout")
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
    for command in COMMANDS.values():
        child = sub.add_parser(command.name, help=command.help, description=command.help)
        command.configure(child)
    return parser


def _write(stream, text: str) -> None:
    data = text if text.endswith("\n") else text + "\n"
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        buffer.write(data.encode("utf-8"))
        buffer.flush()
    else:
        stream.write(data)


def _envelope(name: str, ctx: Optional[Context], outcome: Outcome) -> dict:
    plan = ctx.plan if ctx is not None else None
    return {
        "ok": outcome.code == EXIT_OK,
        "command": name,
        "plan": os.path.abspath(str(plan.path)) if plan is not None else None,
        "tier": plan.tier if plan is not None else None,
        "status": plan.status if plan is not None else None,
        "findings": [finding.to_dict() for finding in outcome.findings],
        "data": outcome.data,
    }


def _finding_line(ctx: Context, finding: Finding) -> str:
    where = ctx.display_path(ctx.plan.path) if ctx.plan is not None else "plan"
    if finding.line is not None:
        where = f"{where}:{finding.line}"
    return f"{where}: {finding.code} {finding.message}"


def emit(name: str, ctx: Optional[Context], outcome: Outcome, as_json: bool, error: Optional[str] = None) -> None:
    if as_json:
        _write(sys.stdout, json.dumps(_envelope(name, ctx, outcome), ensure_ascii=False))
        return
    if ctx is not None:
        stream = sys.stdout if outcome.findings_to_stdout else sys.stderr
        for finding in outcome.findings:
            _write(stream, _finding_line(ctx, finding))
    if outcome.text:
        _write(sys.stdout, outcome.text)
    if error:
        _write(sys.stderr, f"plan_loop: error: {error}")


def _subcommand(argv: List[str]) -> Optional[str]:
    skip = False
    for token in argv:
        if skip:
            skip = False
            continue
        if token in ("--cwd", "--plan"):
            skip = True
            continue
        if not token.startswith("-"):
            return token
    return None


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        name = _subcommand(argv) or ""
        command = COMMANDS.get(name)
        if command is not None and command.always_envelope:
            data = {"decision": "allow", "reason": f"plan-loop: invalid request ({exc})", "status": None}
            if name == "stop":
                data = {"decision": "allow", "reason": data["reason"], "next": None, "stalls": 0}
            emit(name, None, Outcome(EXIT_OK, data=data), True)
            return EXIT_OK
        outcome = Outcome(EXIT_USAGE, data={"error": str(exc)})
        emit(name, None, outcome, "--json" in argv, error=str(exc))
        if "--json" not in argv:
            parser.print_usage(sys.stderr)
        return EXIT_USAGE
    if not args.command:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    command = COMMANDS[args.command]
    ctx = Context(args)
    try:
        outcome = command.run(ctx, args)
    except CliError as exc:
        outcome = Outcome(exc.code, data={"error": str(exc)}, error=str(exc))
    except (OSError, UnicodeDecodeError) as exc:
        error = f"cannot read the plan: {exc}"
        outcome = Outcome(EXIT_USAGE, data={"error": error}, error=error)
    emit(command.name, ctx, outcome, ctx.json or command.always_envelope, error=None if ctx.json else outcome.error)
    return outcome.code


if __name__ == "__main__":
    sys.exit(main())
