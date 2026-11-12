/**
 * plan-loop omp extension core.
 *
 * Finds and runs `skills/plan-loop/scripts/plan_loop.py`, and turns omp events into
 * its `guard` and `stop` requests. Plan grammar and guard policy live in the CLI;
 * this file knows only where `plan/ACTIVE` is and which tool inputs name a write
 * target (plan/plan-loop-dag.spec.md, Part 2 D.2).
 *
 * Every handler fails open: when python or the CLI is missing, fails, or takes
 * longer than 5 seconds, the call is allowed and the session is warned once.
 * A `tool_call` handler that throws or times out would block the tool instead.
 */
import { existsSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import type {
	AgentToolResult,
	ExecOptions,
	ExecResult,
	ExtensionCommandContext,
	ExtensionContext,
	SessionStopEvent,
	SessionStopEventResult,
	ToolCallEvent,
	ToolCallEventResult,
} from "@oh-my-pi/pi-coding-agent";

/** CLI commands the `plan_loop` tool may run. */
export const TOOL_COMMANDS = [
	"check",
	"status",
	"digest",
	"waves",
	"brief",
	"sync",
	"advance",
	"node",
	"scenario",
] as const;
export type ToolCommand = (typeof TOOL_COMMANDS)[number];

/** Commands that change the plan or its state document: the orchestrator's alone. */
export const ORCHESTRATOR_COMMANDS: Readonly<Record<string, true>> = { sync: true, advance: true, node: true, scenario: true };

/** Deadline for the guard and stop calls; past it the call is allowed. */
export const GUARD_TIMEOUT_MS = 5_000;
/** Deadline for the `plan_loop` tool and `/plan-loop status`. */
export const COMMAND_TIMEOUT_MS = 30_000;

const READ_ONLY_LSP_ACTIONS: Readonly<Record<string, true>> = {
	diagnostics: true,
	definition: true,
	type_definition: true,
	implementation: true,
	references: true,
	hover: true,
	symbols: true,
	status: true,
	capabilities: true,
};
const MUTATING_GITHUB_OPS: Readonly<Record<string, true>> = { pr_create: true, pr_checkout: true, pr_push: true };
/** `xd://` devices that never change files. */
const INERT_XD_DEVICES: Readonly<Record<string, true>> = { reject: true, propose: true, report_issue: true };
const XD_PREFIX = "xd://";
const URL_SCHEME = /^([A-Za-z][A-Za-z0-9+.-]*):\/\//;
const CLI_TAIL = ["skills", "plan-loop", "scripts", "plan_loop.py"] as const;
const APPLY_PATCH_START = "*** Begin Patch";

type Env = Record<string, string | undefined>;

/** A `plan_loop.py guard` request without `cwd`. */
export interface GuardRequest {
	tool: "shell" | "patch" | "write";
	command?: string;
	paths?: string[];
	label?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringList(value: unknown): string[] {
	if (!Array.isArray(value)) return [];
	return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

function isNonFileUrl(path: string): boolean {
	const scheme = URL_SCHEME.exec(path.trim())?.[1];
	return scheme !== undefined && scheme.toLowerCase() !== "file";
}

function writeRequest(input: Record<string, unknown>): GuardRequest | null {
	const path = typeof input.path === "string" ? input.path.trim() : "";
	if (path === "") return { tool: "write", paths: [] };
	if (path.toLowerCase().startsWith(XD_PREFIX)) return xdRequest(path.slice(XD_PREFIX.length), input.content);
	if (isNonFileUrl(path)) return null;
	return { tool: "write", paths: [path] };
}

function xdRequest(device: string, content: unknown): GuardRequest | null {
	if (device === "resolve") return { tool: "write", paths: [], label: "xd://resolve" };
	if (device === "" || INERT_XD_DEVICES[device] === true) return null;
	let inner: unknown = content;
	if (typeof content === "string") {
		try {
			inner = JSON.parse(content);
		} catch {
			return null; // the device rejects unreadable content itself
		}
	}
	return isRecord(inner) ? guardRequestFor(device, inner) : null;
}

function editRequest(input: Record<string, unknown>): GuardRequest | null {
	const paths = stringList(input.paths);
	if (typeof input.path === "string" && input.path.trim() !== "" && !paths.includes(input.path)) {
		paths.unshift(input.path);
	}
	if (paths.length === 0) {
		// apply_patch edit mode names its targets only inside the patch body; the CLI's
		// `patch` rule reads its Add/Update/Delete File and Move to lines.
		for (const key of ["input", "_input"]) {
			const body = input[key];
			if (typeof body === "string" && body.trimStart().startsWith(APPLY_PATCH_START)) {
				return { tool: "patch", command: body };
			}
		}
		return { tool: "write", paths: [] };
	}
	const files = paths.filter(path => !isNonFileUrl(path));
	return files.length === 0 ? null : { tool: "write", paths: files };
}

/**
 * The guard request for one tool call (spec Part 2 D.2), or null when the call is
 * allowed without asking the CLI. Only a plan in status `planning` denies anything;
 * the CLI decides that.
 */
export function guardRequestFor(toolName: string, input: unknown): GuardRequest | null {
	const args = isRecord(input) ? input : {};
	switch (toolName) {
		case "bash":
			return { tool: "shell", command: typeof args.command === "string" ? args.command : "" };
		case "write":
			return writeRequest(args);
		case "edit":
			return editRequest(args);
		case "ast_edit":
			return { tool: "write", paths: stringList(args.paths) };
		case "lsp": {
			const action = typeof args.action === "string" ? args.action.trim() : "";
			if (READ_ONLY_LSP_ACTIONS[action.toLowerCase()] === true) return null;
			return { tool: "write", paths: [], label: action ? `lsp ${action}` : "lsp" };
		}
		case "github": {
			const op = typeof args.op === "string" ? args.op : "";
			return MUTATING_GITHUB_OPS[op] === true ? { tool: "write", paths: [], label: `github ${op}` } : null;
		}
		default:
			// eval, task, read tools, MCP and other extensions' tools: out of the guard's reach.
			return null;
	}
}

function isFile(path: string): boolean {
	try {
		return statSync(path).isFile();
	} catch {
		return false;
	}
}

function mtimeOf(path: string): number | null {
	try {
		return statSync(path).mtimeMs;
	} catch {
		return null;
	}
}

/** `plan/ACTIVE` above `cwd`, walking up to the first `.git` root (the CLI's walk). */
export function findActiveMarker(cwd: string): string | null {
	let directory = resolve(cwd);
	for (;;) {
		const marker = join(directory, "plan", "ACTIVE");
		if (isFile(marker)) return marker;
		if (existsSync(join(directory, ".git"))) return null;
		const parent = dirname(directory);
		if (parent === directory) return null;
		directory = parent;
	}
}

export interface CliLocations {
	env: Env;
	/** Real directory of this extension (symlinks resolved). */
	extensionDir: string;
	/** omp agent directory, e.g. `~/.omp/agent`. */
	agentDir: string | undefined;
	homeDir: string;
}

/** Where to look for `plan_loop.py`, in order. */
export function cliCandidates(locations: CliLocations): string[] {
	const candidates: string[] = [];
	const fromEnv = locations.env.PLAN_LOOP_CLI?.trim();
	if (fromEnv) candidates.push(fromEnv);
	candidates.push(resolve(locations.extensionDir, "..", "..", ...CLI_TAIL));
	if (locations.agentDir) candidates.push(join(locations.agentDir, ...CLI_TAIL));
	candidates.push(join(locations.homeDir, ".agents", ...CLI_TAIL));
	return candidates;
}

/** The first candidate that exists: `PLAN_LOOP_CLI`, the checkout, the installed skill. */
export function findCli(locations: CliLocations): string | null {
	return cliCandidates(locations).find(isFile) ?? null;
}

/** The omp agent directory: the host's answer, else `PI_CODING_AGENT_DIR`, else `~/.omp/agent`. */
export function resolveAgentDir(hostAgentDir: (() => unknown) | undefined, env: Env, homeDir: string): string {
	try {
		const dir = hostAgentDir?.();
		if (typeof dir === "string" && dir !== "") return dir;
	} catch {
		// fall through to the documented default
	}
	return env.PI_CODING_AGENT_DIR?.trim() || join(homeDir, ".omp", "agent");
}

interface Envelope {
	plan: string | null;
	tier: string | null;
	status: string | null;
	data: Record<string, unknown>;
	/** First line of the CLI's own reason for failing: its first error finding, else `data.error`. */
	error: string | null;
}

function cliError(findings: unknown, data: Record<string, unknown>): string | null {
	const found = Array.isArray(findings)
		? findings.find(item => isRecord(item) && item.severity === "error" && typeof item.code === "string")
		: undefined;
	let text: string | null = null;
	if (isRecord(found)) text = typeof found.message === "string" ? `${found.code} ${found.message}` : String(found.code);
	else if (typeof data.error === "string") text = data.error;
	return text === null ? null : text.trim().split("\n", 1)[0];
}

/** The CLI's `--json` envelope, or null when stdout is not one. */
export function parseEnvelope(stdout: string): Envelope | null {
	let value: unknown;
	try {
		value = JSON.parse(stdout);
	} catch {
		return null;
	}
	if (!isRecord(value) || !isRecord(value.data)) return null;
	return {
		plan: typeof value.plan === "string" ? value.plan : null,
		tier: typeof value.tier === "string" ? value.tier : null,
		status: typeof value.status === "string" ? value.status : null,
		data: value.data,
		error: cliError(value.findings, value.data),
	};
}

export interface Notice {
	message: string;
	type: "info" | "warning";
}

function count(value: unknown): number {
	return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function unavailableNotice(reason: string): Notice {
	return { message: `plan-loop: unavailable (${reason})`, type: "warning" };
}

/** The one-line `/plan-loop status` notice (spec Part 2 F) for a `status --json` envelope. */
export function statusNotice(envelope: Envelope): Notice {
	const data = envelope.data;
	if (envelope.plan === null) return { message: "plan-loop: no active plan", type: "info" };
	const counts = isRecord(data.counts) ? data.counts : {};
	const legacy = isRecord(data.legacy) ? data.legacy : null;
	let nodes: string;
	let scenarios: string;
	if (legacy) {
		const done = count(legacy.done);
		const open = Array.isArray(legacy.open) ? legacy.open.length : 0;
		nodes = `${done}/${done + open}`;
		scenarios = "0/0";
	} else {
		const all = Array.isArray(data.scenarios) ? data.scenarios : [];
		const passed = all.filter(item => isRecord(item) && item.status === "PASS").length;
		nodes = `${count(counts.done)}/${Array.isArray(data.nodes) ? data.nodes.length : 0}`;
		scenarios = `${passed}/${all.length}`;
	}
	const ready = Array.isArray(data.ready) ? data.ready : [];
	const next = typeof ready[0] === "string" ? ready[0] : "-";
	const slug = typeof data.slug === "string" ? data.slug : envelope.plan;
	const review = typeof data.review === "string" ? data.review : "-";
	return {
		message:
			`plan-loop: ${slug} — status=${envelope.status ?? "-"} tier=${envelope.tier ?? "legacy"} ` +
			`review=${review} nodes=${nodes} blocked=${count(counts.blocked)} scenarios=${scenarios} next=${next}`,
		type: "info",
	};
}

export const PLAN_PROMPT_PREFIX = "Use the plan-loop skill (read skill://plan-loop first) in plan mode for this request:";
export const RUN_PROMPT =
	"Use the plan-loop skill (read skill://plan-loop first) in run mode: execute the active plan named in plan/ACTIVE.";
const USAGE = "Usage: /plan-loop status | plan <request> | run";

export type Exec = (command: string, args: string[], options?: ExecOptions) => Promise<ExecResult>;

export interface PlanLoopDeps {
	exec: Exec;
	/** `pi.sendUserMessage`: starts a turn when idle. */
	sendUserMessage: (text: string) => unknown;
	env: Env;
	extensionDir: string;
	agentDir: () => string | undefined;
	homeDir: string;
}

type CliRun = { ok: true; code: number; stdout: string; stderr: string } | { ok: false; reason: string };

export interface ToolParams {
	command?: unknown;
	args?: unknown;
}

function errorText(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function textResult(text: string, details: Record<string, unknown>, isError = false): AgentToolResult {
	return { content: [{ type: "text", text }], details, ...(isError ? { isError: true } : {}) };
}

/**
 * The `--json` envelope of a run that exited 0, or why there is none. A nonzero exit is
 * a CLI failure even when an envelope came with it (`guard` and `stop` always exit 0;
 * `status` exits 3 when the state document is missing or stale).
 */
function envelopeOrReason(command: string, run: CliRun): Envelope | string {
	if (!run.ok) return run.reason;
	const envelope = parseEnvelope(run.stdout);
	if (run.code === 0 && envelope !== null) return envelope;
	const detail = envelope?.error ?? run.stderr.trim().split("\n", 1)[0];
	const what = run.code === 0 ? `${command} printed no JSON envelope` : `${command} exited ${run.code}`;
	return detail ? `${what}: ${detail}` : what;
}

/** The handlers `index.ts` registers, bound to one session. */
export function createPlanLoop(deps: PlanLoopDeps) {
	let warned = false;
	/** Skip the guard while the plan is not in planning, until the marker or plan file changes. */
	let skip: { marker: string; markerMtime: number; plan: string; planMtime: number } | null = null;

	function warnOnce(ctx: ExtensionContext, reason: string): void {
		if (warned) return;
		warned = true;
		try {
			ctx.ui.notify(`plan-loop: guards are failing open (${reason}).`, "warning");
		} catch {
			// a warning must never block or break the call
		}
	}

	async function runCli(cwd: string, args: string[], timeout: number, signal?: AbortSignal): Promise<CliRun> {
		const cli = findCli({
			env: deps.env,
			extensionDir: deps.extensionDir,
			agentDir: deps.agentDir(),
			homeDir: deps.homeDir,
		});
		if (cli === null) return { ok: false, reason: "plan_loop.py not found; set PLAN_LOOP_CLI" };
		const python = deps.env.PLAN_LOOP_PYTHON?.trim() || "python3";
		let result: ExecResult;
		try {
			result = await deps.exec(python, [cli, "--cwd", cwd, "--json", ...args], { cwd, timeout, signal });
		} catch (error) {
			return { ok: false, reason: `cannot run ${python}: ${errorText(error)}` };
		}
		if (result.killed) {
			return { ok: false, reason: signal?.aborted ? "cancelled" : `no answer within ${timeout / 1000}s` };
		}
		if (typeof result.code !== "number" || result.code < 0) return { ok: false, reason: `${python} did not run` };
		return { ok: true, code: result.code, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
	}

	/** Run a `guard` or `stop` request; the envelope, or null after warning. */
	async function decide(
		ctx: ExtensionContext,
		command: "guard" | "stop",
		request: Record<string, unknown>,
		signal?: AbortSignal,
	): Promise<Envelope | null> {
		const run = await runCli(ctx.cwd, [command, "--request", JSON.stringify(request)], GUARD_TIMEOUT_MS, signal);
		if (signal?.aborted) return null;
		const result = envelopeOrReason(command, run);
		if (typeof result === "string" || typeof result.data.decision !== "string") {
			warnOnce(ctx, typeof result === "string" ? result : `${command} returned no decision`);
			return null;
		}
		return result;
	}

	function skipping(marker: string): boolean {
		if (skip === null || skip.marker !== marker) return false;
		return mtimeOf(marker) === skip.markerMtime && mtimeOf(skip.plan) === skip.planMtime;
	}

	function remember(marker: string, envelope: Envelope): void {
		skip = null;
		const status = envelope.data.status;
		if (typeof status !== "string" || status === "planning" || envelope.plan === null) return;
		const markerMtime = mtimeOf(marker);
		const planMtime = mtimeOf(envelope.plan);
		if (markerMtime !== null && planMtime !== null) skip = { marker, markerMtime, plan: envelope.plan, planMtime };
	}

	async function onToolCall(event: ToolCallEvent, ctx: ExtensionContext): Promise<ToolCallEventResult | undefined> {
		try {
			const request = guardRequestFor(event.toolName, event.input);
			if (request === null) return undefined;
			const marker = findActiveMarker(ctx.cwd);
			if (marker === null || skipping(marker)) return undefined;
			const envelope = await decide(ctx, "guard", { cwd: ctx.cwd, ...request });
			if (envelope === null) return undefined;
			remember(marker, envelope);
			if (envelope.data.decision !== "deny") return undefined;
			const reason = envelope.data.reason;
			return { block: true, reason: typeof reason === "string" && reason ? reason : "plan-loop: blocked while planning." };
		} catch (error) {
			warnOnce(ctx, errorText(error));
			return undefined;
		}
	}

	async function onSessionStop(
		event: SessionStopEvent,
		ctx: ExtensionContext,
	): Promise<SessionStopEventResult | undefined> {
		try {
			if (findActiveMarker(ctx.cwd) === null) return undefined;
			const request = { cwd: ctx.cwd, session_id: event.session_id };
			const envelope = await decide(ctx, "stop", request, event.signal);
			if (envelope === null || envelope.data.decision !== "continue") return undefined;
			const reason = envelope.data.reason;
			return {
				decision: "block",
				reason: typeof reason === "string" && reason ? reason : "plan-loop: the active plan has work left.",
			};
		} catch (error) {
			warnOnce(ctx, errorText(error));
			return undefined;
		}
	}

	async function executeTool(
		_toolCallId: string,
		params: ToolParams,
		signal: AbortSignal | undefined,
		_onUpdate: unknown,
		ctx: ExtensionContext,
	): Promise<AgentToolResult> {
		const command = params?.command;
		const args = params?.args ?? [];
		if (typeof command !== "string" || !(TOOL_COMMANDS as readonly string[]).includes(command)) {
			return textResult(`plan-loop: unknown command ${JSON.stringify(command)}; use one of ${TOOL_COMMANDS.join(", ")}.`, { command }, true);
		}
		if (!Array.isArray(args) || !args.every(item => typeof item === "string")) {
			return textResult("plan-loop: args must be a list of strings.", { command }, true);
		}
		if (ctx?.agent?.kind === "sub" && ORCHESTRATOR_COMMANDS[command] === true) {
			return textResult(
				`plan-loop: ${command} changes the plan; only the orchestrator (main session) runs it. Report your result instead.`,
				{ command, args, refused: true },
				true,
			);
		}
		const run = await runCli(ctx.cwd, [command, ...args], COMMAND_TIMEOUT_MS, signal);
		if (!run.ok) return textResult(unavailableNotice(run.reason).message, { command, args }, true);
		const parts = [`exit code: ${run.code}`, run.stdout.trimEnd()];
		if (run.stderr.trim()) parts.push(`stderr:\n${run.stderr.trimEnd()}`);
		return textResult(parts.filter(Boolean).join("\n"), {
			command,
			args,
			exitCode: run.code,
			stdout: run.stdout,
			stderr: run.stderr,
		});
	}

	async function startSkill(ctx: ExtensionCommandContext, prompt: string): Promise<void> {
		const modes = ctx.sessionModes;
		const plan = modes?.getState().plan.status;
		if (modes && plan !== undefined && plan !== "inactive") {
			const result = await modes.set({ mode: "plan", action: "exit" });
			if (!result.ok) {
				ctx.ui.notify(`plan-loop: could not leave built-in plan mode (${result.message}); leave it, then retry.`, "warning");
				return;
			}
		}
		const failed = (error: unknown) => {
			try {
				ctx.ui.notify(`plan-loop: the request was not sent (${errorText(error)}).`, "warning");
			} catch {
				// nothing left to report to
			}
		};
		try {
			const sent = deps.sendUserMessage(prompt);
			if (sent instanceof Promise) sent.catch(failed);
		} catch (error) {
			failed(error);
		}
	}

	async function onCommand(args: string, ctx: ExtensionCommandContext): Promise<void> {
		try {
			const text = args.trim();
			const space = text.search(/\s/);
			const sub = space === -1 ? text : text.slice(0, space);
			const rest = space === -1 ? "" : text.slice(space).trim();
			if (sub === "status" && rest === "") {
				const result = envelopeOrReason("status", await runCli(ctx.cwd, ["status"], COMMAND_TIMEOUT_MS));
				const notice = typeof result === "string" ? unavailableNotice(result) : statusNotice(result);
				ctx.ui.notify(notice.message, notice.type);
			} else if (sub === "plan" && rest !== "") {
				await startSkill(ctx, `${PLAN_PROMPT_PREFIX}\n\n${rest}`);
			} else if (sub === "run" && rest === "") {
				await startSkill(ctx, RUN_PROMPT);
			} else {
				ctx.ui.notify(USAGE, "warning");
			}
		} catch (error) {
			try {
				ctx.ui.notify(unavailableNotice(errorText(error)).message, "warning");
			} catch {
				// nothing left to report to
			}
		}
	}

	return { onToolCall, onSessionStop, executeTool, onCommand };
}
