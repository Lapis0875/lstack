// Unit tests for the plan-loop omp extension: a fake `pi`, an injected exec, and the
// real CLI on temporary repositories built from tests/plan-loop/fixtures.
// Test names carry the tags [E01]–[E18] from plan/plan-loop-dag.md (Contracts M-4).
import { afterAll, afterEach, beforeEach, describe, expect, test } from "bun:test";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { ExecOptions, ExecResult } from "@oh-my-pi/pi-coding-agent";
import { cliCandidates, findCli, GUARD_TIMEOUT_MS, guardRequestFor, RUN_PROMPT, TOOL_COMMANDS } from "../core";
import extension from "../index";

const REPO = realpathSync(resolve(import.meta.dir, "..", "..", ".."));
const CLI = join(REPO, "skills", "plan-loop", "scripts", "plan_loop.py");
const FIXTURES = join(REPO, "tests", "plan-loop", "fixtures");
const PLANNING = "plan-loop: team-ok.md is still in planning (read-only outside plan/).";
const ENV_KEYS = ["PLAN_LOOP_CLI", "PLAN_LOOP_PYTHON"] as const;

const temps: string[] = [];
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
	for (const key of ENV_KEYS) {
		savedEnv[key] = process.env[key];
		delete process.env[key];
	}
});

afterEach(() => {
	for (const key of ENV_KEYS) {
		if (savedEnv[key] === undefined) delete process.env[key];
		else process.env[key] = savedEnv[key];
	}
});

afterAll(() => {
	for (const dir of temps) rmSync(dir, { recursive: true, force: true });
});

function tempDir(): string {
	const dir = realpathSync(mkdtempSync(join(tmpdir(), "plan-loop-ext-")));
	temps.push(dir);
	return dir;
}

/** A repository root with `.git`; with a slug, the fixture is the active plan (the at.sh `mk`). */
function repo(slug?: string): string {
	const root = join(tempDir(), "r");
	mkdirSync(join(root, "plan"), { recursive: true });
	mkdirSync(join(root, ".git"));
	if (slug) {
		cpSync(join(FIXTURES, `${slug}.md`), join(root, "plan", `${slug}.md`));
		writeFileSync(join(root, "plan", "ACTIVE"), `${slug}\n`);
	}
	return root;
}

function runCli(root: string, ...args: string[]): void {
	const result = Bun.spawnSync(["python3", CLI, "--cwd", root, ...args]);
	if (result.exitCode !== 0) throw new Error(`${args.join(" ")}: exit ${result.exitCode}: ${result.stderr}`);
}

/** Spawns for real, with omp's ExecResult shape; a missing binary rejects like omp's exec. */
async function realExec(command: string, args: string[], options: ExecOptions = {}): Promise<ExecResult> {
	const proc = Bun.spawn([command, ...args], {
		cwd: options.cwd,
		stdout: "pipe",
		stderr: "pipe",
		timeout: options.timeout,
		signal: options.signal,
	});
	const [stdout, stderr, code] = await Promise.all([
		new Response(proc.stdout).text(),
		new Response(proc.stderr).text(),
		proc.exited,
	]);
	// Bun reports `killed: true` after a normal exit too; a signal code marks a real kill.
	const killed = proc.signalCode !== null;
	return { stdout, stderr, code: killed ? -1 : code, killed };
}

interface Call {
	command: string;
	args: string[];
	options?: ExecOptions;
}

function fakeExec(answer: (call: Call) => ExecResult | Promise<ExecResult>) {
	const calls: Call[] = [];
	const exec = async (command: string, args: string[], options?: ExecOptions) => {
		const call = { command, args, options };
		calls.push(call);
		return answer(call);
	};
	return { exec, calls };
}

function envelope(data: Record<string, unknown>, top: Record<string, unknown> = {}, code = 0): ExecResult {
	const value = { ok: code === 0, command: "guard", plan: null, tier: null, status: null, findings: [], data, ...top };
	return { stdout: JSON.stringify(value), stderr: "", code, killed: false };
}

const noAnswer = (): ExecResult => {
	throw new Error("the CLI must not be called");
};

/** The zod-like builder the extension calls; records each schema's definition. */
interface Schema {
	readonly [field: string]: unknown;
	describe(): Schema;
	optional(): Schema;
}

interface ToolResult {
	content: Array<{ type: string; text: string }>;
	details: Record<string, unknown>;
	isError?: boolean;
}

interface RegisteredTool {
	name: string;
	approval: string;
	parameters: { shape: { command: { values: readonly string[] } } };
	execute(id: string, params: Record<string, unknown>, signal: undefined, onUpdate: undefined, ctx: unknown): Promise<ToolResult>;
}

interface RegisteredCommand {
	name: string;
	handler(args: string, ctx: unknown): Promise<void>;
}

/** Loads index.ts against a fake `pi` and returns what it registered. */
function load(exec: (command: string, args: string[], options?: ExecOptions) => Promise<ExecResult>) {
	const handlers: Record<string, (event: unknown, ctx: unknown) => Promise<unknown>> = {};
	const sent: string[] = [];
	let tool: RegisteredTool | undefined;
	let command: RegisteredCommand | undefined;
	const schema = (def: Record<string, unknown>): Schema => ({
		...def,
		describe() {
			return this;
		},
		optional() {
			return schema({ ...def, optional: true });
		},
	});
	const pi = {
		zod: {
			object: (shape: unknown) => schema({ kind: "object", shape }),
			enum: (values: unknown) => schema({ kind: "enum", values }),
			array: (element: unknown) => schema({ kind: "array", element }),
			string: () => schema({ kind: "string" }),
		},
		pi: { getAgentDir: () => join(tmpdir(), "plan-loop-ext-no-agent-dir") },
		exec,
		on: (event: string, handler: (event: unknown, ctx: unknown) => Promise<unknown>) => {
			handlers[event] = handler;
		},
		registerTool: (definition: RegisteredTool) => {
			tool = definition;
		},
		registerCommand: (name: string, definition: Omit<RegisteredCommand, "name">) => {
			command = { name, ...definition };
		},
		sendUserMessage: (text: string) => {
			sent.push(text);
			return Promise.resolve();
		},
	};
	extension(pi as never);
	if (!tool || !command) throw new Error("index.ts did not register the plan_loop tool and the /plan-loop command");
	return {
		guard: (toolName: string, input: unknown, ctx: unknown) =>
			handlers.tool_call({ type: "tool_call", toolCallId: "call-1", toolName, input }, ctx),
		stop: (sessionId: string, ctx: unknown) =>
			handlers.session_stop(
				{
					type: "session_stop",
					messages: [],
					turn_id: 1,
					session_id: sessionId,
					stop_hook_active: false,
					signal: new AbortController().signal,
				},
				ctx,
			),
		tool,
		command,
		sent,
	};
}

function context(cwd: string, extra: Record<string, unknown> = {}) {
	const notes: Array<[string, string]> = [];
	return {
		cwd,
		agent: { kind: "main", id: "Main", name: "main", depth: 0 },
		ui: { notify: (message: string, type: string) => notes.push([message, type]) },
		notes,
		...extra,
	};
}

function sessionId(tag: string): string {
	return `omp-ext-${tag}-${process.pid}-${Date.now()}`;
}

describe("guard (tool_call)", () => {
	test("[E01] denies a write outside plan/ while the plan is planning", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		const ctx = context(root);
		expect(await guard("write", { path: "src/a.py", content: "x" }, ctx)).toEqual({
			block: true,
			reason: `${PLANNING} Blocked src/a.py. Finish the plan and get approval first.`,
		});
		expect(ctx.notes).toEqual([]);
	});

	test("[E02] allows a write inside plan/ while the plan is planning", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		const ctx = context(root);
		expect(await guard("write", { path: "plan/notes.md", content: "x" }, ctx)).toBeUndefined();
		expect(await guard("write", { path: join(root, "plan", "team-ok.md"), content: "x" }, ctx)).toBeUndefined();
		expect(await guard("edit", { path: "plan/team-ok.md", input: "…" }, ctx)).toBeUndefined();
		expect(ctx.notes).toEqual([]);
	});

	test("[E03] lets a write to a non-file scheme through without calling the CLI", async () => {
		const root = repo("team-ok");
		const { exec, calls } = fakeExec(noAnswer);
		const { guard } = load(exec);
		expect(await guard("write", { path: "local://notes.md", content: "x" }, context(root))).toBeUndefined();
		expect(await guard("write", { path: "skill://plan-loop/x.md", content: "x" }, context(root))).toBeUndefined();
		expect(await guard("edit", { paths: ["local://a.md"], input: "…" }, context(root))).toBeUndefined();
		expect(calls).toHaveLength(0);
		expect(guardRequestFor("write", { path: "file:///repo/src/a.py" })).toEqual({
			tool: "write",
			paths: ["file:///repo/src/a.py"],
		});
	});

	test("[E04] denies an edit whose target path cannot be read while planning", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		expect(guardRequestFor("edit", { input: "no file header" })).toEqual({ tool: "write", paths: [] });
		expect(await guard("edit", { input: "no file header" }, context(root))).toEqual({
			block: true,
			reason: `${PLANNING} Blocked a change with no known target path. Finish the plan and get approval first.`,
		});
	});

	test("[E05] denies write xd://resolve while planning", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		expect(await guard("write", { path: "xd://resolve", content: '{"reason":"apply"}' }, context(root))).toEqual({
			block: true,
			reason: `${PLANNING} Blocked xd://resolve. Finish the plan and get approval first.`,
		});
		for (const device of ["reject", "propose", "report_issue"]) {
			expect(guardRequestFor("write", { path: `xd://${device}`, content: "{}" })).toBeNull();
		}
	});

	test("[E06] judges write xd://ast_edit by the paths in its content", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		const content = (paths: string[]) => JSON.stringify({ ops: [{ pat: "a", out: "b" }], paths });
		expect(guardRequestFor("write", { path: "xd://ast_edit", content: content(["src/a.ts"]) })).toEqual({
			tool: "write",
			paths: ["src/a.ts"],
		});
		expect(guardRequestFor("write", { path: "xd://ast_edit", content: "not json" })).toBeNull();
		expect(await guard("write", { path: "xd://ast_edit", content: content(["src/a.ts"]) }, context(root))).toEqual({
			block: true,
			reason: `${PLANNING} Blocked src/a.ts. Finish the plan and get approval first.`,
		});
		expect(
			await guard("write", { path: "xd://ast_edit", content: content(["plan/team-ok.md"]) }, context(root)),
		).toBeUndefined();
	});

	test("[E07] allows read-only lsp actions and denies the others while planning", async () => {
		const root = repo("team-ok");
		const fake = fakeExec(noAnswer);
		for (const action of ["diagnostics", "hover", "references", "symbols", "capabilities"]) {
			expect(await load(fake.exec).guard("lsp", { action, file: "src/a.ts" }, context(root))).toBeUndefined();
		}
		expect(fake.calls).toHaveLength(0);
		expect(await load(realExec).guard("lsp", { action: "rename", file: "src/a.ts" }, context(root))).toEqual({
			block: true,
			reason: `${PLANNING} Blocked lsp rename. Finish the plan and get approval first.`,
		});
	});

	test("[E08] allows eval", async () => {
		const root = repo("team-ok");
		const { exec, calls } = fakeExec(noAnswer);
		const { guard } = load(exec);
		const input = { cells: [{ language: "py", code: "open('src/a.py', 'w').write('x')" }] };
		expect(await guard("eval", input, context(root))).toBeUndefined();
		expect(calls).toHaveLength(0);
	});

	test("[E09] does not call the CLI when there is no plan/ACTIVE", async () => {
		const root = repo();
		const { exec, calls } = fakeExec(noAnswer);
		const { guard, stop } = load(exec);
		const ctx = context(join(root, "plan"));
		expect(await guard("bash", { command: "rm -rf src" }, ctx)).toBeUndefined();
		expect(await guard("write", { path: "src/a.py", content: "x" }, ctx)).toBeUndefined();
		expect(await stop(sessionId("e09"), ctx)).toBeUndefined();
		expect(calls).toHaveLength(0);
		expect(ctx.notes).toEqual([]);
	});

	test("[E10] allows the call and warns once per session when python is missing", async () => {
		process.env.PLAN_LOOP_PYTHON = "/nonexistent";
		const root = repo("team-ok");
		const { guard } = load(realExec);
		const ctx = context(root);
		expect(await guard("write", { path: "src/a.py", content: "x" }, ctx)).toBeUndefined();
		expect(await guard("bash", { command: "rm -rf src" }, ctx)).toBeUndefined();
		expect(ctx.notes).toHaveLength(1);
		const [message, type] = ctx.notes[0];
		expect(type).toBe("warning");
		expect(message).toStartWith("plan-loop: guards are failing open (cannot run /nonexistent:");
	});

	test("[E11] never throws on a CLI error or timeout and allows the call", async () => {
		const root = repo("team-ok");
		const failures: Array<(call: Call) => ExecResult> = [
			() => ({ stdout: "", stderr: "", code: -1, killed: true }),
			() => ({ stdout: "", stderr: "Traceback (most recent call last):\nboom", code: 1, killed: false }),
			() => ({ stdout: "not json", stderr: "", code: 0, killed: false }),
			() => envelope({ unexpected: true }),
			() => {
				throw new Error("spawn failed");
			},
		];
		for (const failure of failures) {
			const { exec, calls } = fakeExec(failure);
			const { guard, stop } = load(exec);
			const ctx = context(root);
			await expect(guard("write", { path: "src/a.py", content: "x" }, ctx)).resolves.toBeUndefined();
			await expect(stop(sessionId("e11"), ctx)).resolves.toBeUndefined();
			expect(calls[0].options?.timeout).toBe(GUARD_TIMEOUT_MS);
			expect(ctx.notes).toHaveLength(1);
			expect(ctx.notes[0][1]).toBe("warning");
		}
	});

	test("bash commands follow the shell rules while planning", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		expect(await guard("bash", { command: "rm -rf src" }, context(root))).toEqual({
			block: true,
			reason: `${PLANNING} This shell command looks mutating. Use read-only commands until the plan is approved.`,
		});
		expect(await guard("bash", { command: "ls -la" }, context(root))).toBeUndefined();
		expect(guardRequestFor("github", { op: "pr_push" })).toEqual({ tool: "write", paths: [], label: "github pr_push" });
		expect(guardRequestFor("github", { op: "repo_view" })).toBeNull();
	});

	test("apply_patch edits are judged by the targets in the patch body while planning", async () => {
		const root = repo("team-ok");
		const { guard } = load(realExec);
		const patch = (...lines: string[]) => ["*** Begin Patch", ...lines, "*** End Patch"].join("\n");
		const blocked = (target: string) => ({
			block: true,
			reason: `${PLANNING} Blocked edit to: ${target}. Finish the plan and get approval first.`,
		});
		const inside = patch("*** Update File: plan/team-ok.md", "@@", "+note");
		expect(guardRequestFor("edit", { input: inside })).toEqual({ tool: "patch", command: inside });
		expect(await guard("edit", { input: inside }, context(root))).toBeUndefined();
		expect(await guard("edit", { _input: patch("*** Add File: src/a.py", "+x") }, context(root))).toEqual(
			blocked("src/a.py"),
		);
		const moved = patch("*** Update File: plan/team-ok.md", "*** Move to: src/plan.md", "@@", "+x");
		expect(await guard("edit", { input: moved }, context(root))).toEqual(blocked("src/plan.md"));
	});

	test("skips the CLI while the plan is not planning, until the plan file changes", async () => {
		const root = repo("team-ok");
		const plan = join(root, "plan", "team-ok.md");
		const { exec, calls } = fakeExec(() =>
			envelope({ decision: "allow", reason: "", status: "running" }, { plan, status: "running" }),
		);
		const { guard } = load(exec);
		const ctx = context(root);
		expect(await guard("bash", { command: "rm -rf build" }, ctx)).toBeUndefined();
		expect(await guard("bash", { command: "rm -rf build" }, ctx)).toBeUndefined();
		expect(calls).toHaveLength(1);
		const later = new Date(Date.now() + 5_000);
		utimesSync(plan, later, later);
		expect(await guard("bash", { command: "rm -rf build" }, ctx)).toBeUndefined();
		expect(calls).toHaveLength(2);
	});

	test("fails open when the CLI exits nonzero, even with a deny decision", async () => {
		const root = repo("team-ok");
		const deny = { decision: "deny", reason: `${PLANNING} Blocked src/a.py.`, status: "planning" };
		const { exec, calls } = fakeExec(() => envelope(deny, { status: "planning" }, 1));
		const { guard } = load(exec);
		const ctx = context(root);
		expect(await guard("write", { path: "src/a.py", content: "x" }, ctx)).toBeUndefined();
		expect(await guard("bash", { command: "rm -rf src" }, ctx)).toBeUndefined();
		expect(calls).toHaveLength(2);
		expect(ctx.notes).toEqual([["plan-loop: guards are failing open (guard exited 1).", "warning"]]);
	});
});

describe("stop guard (session_stop)", () => {
	test("[E12] blocks the stop while a running plan has a ready node", async () => {
		const root = repo("team-ok");
		runCli(root, "advance", "approved");
		runCli(root, "advance", "running");
		const { stop } = load(realExec);
		const result = (await stop(sessionId("e12"), context(root))) as { decision: string; reason: string };
		expect(result.decision).toBe("block");
		expect(result.reason).toContain("N1");
		expect(Object.keys(result).sort()).toEqual(["decision", "reason"]);
	});

	test("[E13] returns nothing when the CLI allows the stop", async () => {
		const root = repo("team-ok");
		expect(await load(realExec).stop(sessionId("e13"), context(root))).toBeUndefined();
		const { exec, calls } = fakeExec(() => envelope({ decision: "allow", reason: "", next: null, stalls: 0 }));
		const ctx = context(root);
		expect(await load(exec).stop(sessionId("e13b"), ctx)).toBeUndefined();
		expect(calls[0].args.slice(1, 5)).toEqual(["--cwd", root, "--json", "stop"]);
		expect(JSON.parse(calls[0].args[6])).toEqual({ cwd: root, session_id: expect.stringContaining("e13b") });
		expect(ctx.notes).toEqual([]);
	});

	test("fails open when the CLI exits nonzero, even with a continue decision", async () => {
		const root = repo("team-ok");
		const findings = [{ code: "E-STATE-SCHEMA", severity: "error", message: "bad state\nsecond line", line: 1, node: null }];
		const proceed = { decision: "continue", reason: "plan-loop: N1 is ready.", next: "N1", stalls: 0 };
		const { exec } = fakeExec(() => envelope(proceed, { findings }, 2));
		const { stop } = load(exec);
		const ctx = context(root);
		expect(await stop(sessionId("nonzero-a"), ctx)).toBeUndefined();
		expect(await stop(sessionId("nonzero-b"), ctx)).toBeUndefined();
		expect(ctx.notes).toEqual([
			["plan-loop: guards are failing open (stop exited 2: E-STATE-SCHEMA bad state).", "warning"],
		]);
	});
});

describe("plan_loop tool", () => {
	test("[E14] passes command and args with --cwd and --json and returns stdout and exit code", async () => {
		const root = repo("team-ok");
		const stdout = '{"ok": false, "command": "node"}\n';
		const { exec, calls } = fakeExec(() => ({ stdout, stderr: "", code: 4, killed: false }));
		const { tool } = load(exec);
		expect(tool.name).toBe("plan_loop");
		expect(tool.approval).toBe("write");
		expect(tool.parameters.shape.command.values).toEqual(TOOL_COMMANDS);
		const args = ["done", "N1", "--evidence", "pytest ok"];
		const result = await tool.execute("call-1", { command: "node", args }, undefined, undefined, context(root));
		expect(calls).toHaveLength(1);
		expect(calls[0].command).toBe("python3");
		expect(calls[0].args).toEqual([CLI, "--cwd", root, "--json", "node", ...args]);
		expect(calls[0].options?.cwd).toBe(root);
		expect(result.content[0].text).toBe(`exit code: 4\n${stdout.trimEnd()}`);
		expect(result.details).toMatchObject({ command: "node", args, exitCode: 4, stdout });
		expect(result.isError).toBeUndefined();

		const real = await load(realExec).tool.execute("call-2", { command: "status" }, undefined, undefined, context(root));
		expect(real.details.exitCode).toBe(0);
		expect(JSON.parse(String(real.details.stdout)).data.slug).toBe("team-ok");
	});

	test("[E15] refuses sync, advance, node and scenario in a subagent", async () => {
		const root = repo("team-ok");
		const { exec, calls } = fakeExec(() => envelope({}));
		const { tool } = load(exec);
		const sub = context(root, { agent: { kind: "sub", id: "0-Worker", name: "worker", depth: 1 } });
		for (const command of ["sync", "advance", "node", "scenario"]) {
			const result = await tool.execute("call-1", { command, args: ["x"] }, undefined, undefined, sub);
			expect(result.isError).toBe(true);
			expect(result.content[0].text).toContain("only the orchestrator");
		}
		expect(calls).toHaveLength(0);
		await tool.execute("call-2", { command: "status" }, undefined, undefined, sub);
		await tool.execute("call-3", { command: "node", args: ["done", "N1"] }, undefined, undefined, context(root));
		expect(calls.map(call => call.args[4])).toEqual(["status", "node"]);
	});
});

describe("/plan-loop command", () => {
	test("[E16] status notifies one line without a model turn", async () => {
		const { command, sent } = load(realExec);
		expect(command.name).toBe("plan-loop");
		const ctx = context(repo("team-ok"));
		await command.handler("status", ctx);
		expect(ctx.notes).toEqual([
			[
				"plan-loop: team-ok — status=planning tier=team review=pending nodes=0/5 blocked=0 scenarios=0/2 next=N1",
				"info",
			],
		]);
		const legacy = context(repo("legacy-running"));
		await command.handler("status", legacy);
		expect(legacy.notes).toEqual([
			[
				"plan-loop: legacy-running — status=running tier=legacy review=- nodes=1/3 blocked=0 scenarios=0/0 next=-",
				"info",
			],
		]);
		const none = context(repo());
		await command.handler(" status ", none);
		expect(none.notes).toEqual([["plan-loop: no active plan", "info"]]);
		process.env.PLAN_LOOP_PYTHON = "/nonexistent";
		const broken = context(repo("team-ok"));
		await command.handler("status", broken);
		expect(broken.notes).toHaveLength(1);
		expect(broken.notes[0][0]).toStartWith("plan-loop: unavailable (cannot run /nonexistent:");
		expect(broken.notes[0][1]).toBe("warning");
		expect(sent).toEqual([]);
	});

	test("status reports a nonzero CLI exit as unavailable, with the CLI's reason", async () => {
		const root = repo("workflow-ok");
		runCli(root, "advance", "approved");
		runCli(root, "advance", "running");
		const { command, sent } = load(realExec);
		rmSync(join(root, "plan", "workflow-ok.state.json"));
		const missing = context(root);
		await command.handler("status", missing);
		expect(missing.notes).toEqual([
			[
				"plan-loop: unavailable (status exited 3: E-STATE-MISSING plan/workflow-ok.state.json does not exist; run sync)",
				"warning",
			],
		]);
		runCli(root, "sync");
		const plan = join(root, "plan", "workflow-ok.md");
		writeFileSync(plan, `${readFileSync(plan, "utf8")}\n`);
		const stale = context(root);
		await command.handler("status", stale);
		expect(stale.notes).toEqual([
			[
				"plan-loop: unavailable (status exited 3: E-STATE-STALE plan/workflow-ok.state.json was synced from a different plan file; run sync)",
				"warning",
			],
		]);

		const error = { stdout: JSON.stringify({ ok: false, command: "status", plan: null, tier: null, status: null, findings: [], data: { error: "cannot read the plan: denied" } }), stderr: "", code: 2, killed: false };
		const noEnvelope = { stdout: "", stderr: "Traceback (most recent call last):\n  boom", code: 1, killed: false };
		for (const [answer, expected] of [
			[error, "plan-loop: unavailable (status exited 2: cannot read the plan: denied)"],
			[noEnvelope, "plan-loop: unavailable (status exited 1: Traceback (most recent call last):)"],
		] as const) {
			const ctx = context(root);
			await load(fakeExec(() => answer).exec).command.handler("status", ctx);
			expect(ctx.notes).toEqual([[expected, "warning"]]);
		}
		expect(sent).toEqual([]);
	});

	test("[E17] plan and run leave built-in plan mode, then send the skill request", async () => {
		const { exec, calls } = fakeExec(noAnswer);
		const { command, sent } = load(exec);
		const events: string[] = [];
		let planStatus = "active";
		const modes = {
			getState: () => ({ plan: { status: planStatus }, vibe: { status: "inactive" }, goal: { status: "inactive" }, loop: { status: "inactive" } }),
			set: async (request: { mode: string; action: string }) => {
				events.push(`set ${request.mode} ${request.action} (sent ${sent.length})`);
				planStatus = "inactive";
				return { ok: true, changed: true, state: modes.getState() };
			},
		};
		const root = repo("team-ok");
		await command.handler("plan import orders from CSV", context(root, { sessionModes: modes }));
		expect(events).toEqual(["set plan exit (sent 0)"]);
		expect(sent).toHaveLength(1);
		expect(sent[0]).toContain("plan-loop skill");
		expect(sent[0]).toContain("plan mode");
		expect(sent[0]).toEndWith("import orders from CSV");

		await command.handler("run", context(root, { sessionModes: modes }));
		expect(events).toHaveLength(1);
		expect(sent[1]).toBe(RUN_PROMPT);

		planStatus = "active";
		const refused = context(root, {
			sessionModes: { getState: modes.getState, set: async () => ({ ok: false, code: "busy", message: "a turn is running" }) },
		});
		await command.handler("run", refused);
		expect(sent).toHaveLength(2);
		expect(refused.notes).toEqual([
			["plan-loop: could not leave built-in plan mode (a turn is running); leave it, then retry.", "warning"],
		]);

		await command.handler("run", context(root));
		expect(sent).toHaveLength(3);
		const usage = context(root);
		await command.handler("plan", usage);
		expect(usage.notes).toEqual([["Usage: /plan-loop status | plan <request> | run", "warning"]]);
		expect(calls).toHaveLength(0);
	});
});

describe("CLI discovery", () => {
	test("[E18] finds the CLI at PLAN_LOOP_CLI, then the checkout, then the installed skill", async () => {
		const base = tempDir();
		const tail = ["skills", "plan-loop", "scripts", "plan_loop.py"];
		const fromEnv = join(base, "custom", "plan_loop.py");
		const extensionDir = join(base, "checkout", "omp", "plan-loop");
		const checkout = join(base, "checkout", ...tail);
		const agentDir = join(base, "agent");
		const installed = join(agentDir, ...tail);
		const homeDir = join(base, "home");
		const shared = join(homeDir, ".agents", ...tail);
		const locations = { env: { PLAN_LOOP_CLI: fromEnv }, extensionDir, agentDir, homeDir };
		expect(cliCandidates(locations)).toEqual([fromEnv, checkout, installed, shared]);
		for (const file of [fromEnv, checkout, installed, shared]) {
			mkdirSync(dirname(file), { recursive: true });
			writeFileSync(file, "");
		}
		for (const expected of [fromEnv, checkout, installed, shared]) {
			expect(findCli(locations)).toBe(expected);
			rmSync(expected);
		}
		expect(findCli(locations)).toBeNull();

		const { exec, calls } = fakeExec(() => envelope({}));
		const { tool } = load(exec);
		await tool.execute("call-1", { command: "status" }, undefined, undefined, context(repo("team-ok")));
		expect(calls[0].args[0]).toBe(CLI);
		process.env.PLAN_LOOP_CLI = fromEnv;
		writeFileSync(fromEnv, "");
		await tool.execute("call-2", { command: "status" }, undefined, undefined, context(repo("team-ok")));
		expect(calls[1].args[0]).toBe(fromEnv);
	});
});
