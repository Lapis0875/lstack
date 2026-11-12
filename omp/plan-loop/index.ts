// plan-loop for omp: planning write guard, stop guard, the `plan_loop` tool and
// the `/plan-loop` command. Plan rules live in skills/plan-loop/scripts/plan_loop.py;
// core.ts finds that CLI and maps omp events onto it. Install with install.py.
import { realpathSync } from "node:fs";
import { homedir } from "node:os";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { createPlanLoop, resolveAgentDir, TOOL_COMMANDS } from "./core";

export default function planLoopExtension(pi: ExtensionAPI): void {
	const here = fileURLToPath(import.meta.url);
	let agentDir: string | undefined;
	const planLoop = createPlanLoop({
		exec: (command, args, options) => pi.exec(command, args, options),
		sendUserMessage: text => pi.sendUserMessage(text),
		env: process.env,
		extensionDir: dirname(realpathSync(here)),
		agentDir: () => {
			agentDir ??= resolveAgentDir(() => pi.pi.getAgentDir(), process.env, homedir());
			return agentDir;
		},
		homeDir: homedir(),
	});

	pi.on("tool_call", planLoop.onToolCall);
	pi.on("session_stop", planLoop.onSessionStop);

	const z = pi.zod;
	pi.registerTool({
		name: "plan_loop",
		label: "Plan Loop",
		description:
			"Run the plan-loop CLI on the active plan (plan/ACTIVE) and return its JSON output and exit code. " +
			"check, status, digest, waves and brief read; sync, advance, node and scenario change the plan " +
			"and its state document and are refused in subagents.",
		parameters: z.object({
			command: z.enum(TOOL_COMMANDS).describe("plan_loop.py command"),
			args: z
				.array(z.string())
				.optional()
				.describe('arguments after the command, e.g. ["done", "N1", "--evidence", "pytest ok"]'),
		}),
		approval: "write",
		execute: planLoop.executeTool,
	});

	pi.registerCommand("plan-loop", {
		description: "plan-loop: /plan-loop status | plan <request> | run",
		handler: planLoop.onCommand,
	});
}
