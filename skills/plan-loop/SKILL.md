---
name: plan-loop
description: >-
  Plan-then-execute harness ported from omp's plan mode, todo tracking, and
  goal loop. `plan` mode investigates read-only and writes one plan file
  (plan/<slug>.md) holding the user's request, requirements, mandatory
  acceptance scenarios, and a References section that pins official docs from
  the repository's Context7 reference pack (docs/refs/); an independent
  reviewer checks the plan before the user approves it. Under a dev-team
  workflow the tasks form a DAG of waves with an owner per node; on request
  the plan becomes a workflow with node briefs and a JSON state record. `run`
  mode executes the approved plan with live progress, per-task verification,
  recorded scenario results, and a final smoke run, continuing until every
  task is done or blocked. Use when the user asks to plan before implementing,
  "계획 세우고 구현", "plan-loop", "plan mode", "execute the plan", or wants a
  long task driven to completion.
---

# plan-loop

Two modes over one file. `plan` produces `plan/<slug>.md`, has it reviewed,
and stops for approval. `run` executes an approved plan until it is done. The
plan file is the single source of truth for scope, references, scenarios,
tasks, and evidence; chat history is not. Run the session in the user's
language; section names, field names, and IDs stay as the templates write them.

Works in Codex CLI and omp:

| Concern | Codex | omp |
| --- | --- | --- |
| Live progress | `update_plan` | `todo` tool |
| Approval | ask the user, wait for an explicit yes | `ask` |
| Keep going until done | `/goal`, plus the optional Stop hook in `codex/plan-loop/` | goal mode, plus the optional extension's stop guard |
| Read-only planning | this skill's rules, plus the optional PreToolUse hook | this skill's rules, plus the optional omp extension guard; leave built-in plan mode first |
| Subagents (team tier) | see `references/team-workflow.md` | `task`; see `references/team-workflow.md` |
| Docs lookup | `docs/refs/`, then Context7 MCP `query-docs` or `ctx7 docs` | same |

omp's built-in plan mode cannot write `plan/<slug>.md` and fixes its own plan
location, sections, and approval step, so this skill runs outside it: if
built-in plan mode is on, turn it off first. Nothing in this skill needs the
omp extension; it only adds guards, a tool, and a command (last section).

## Files

```
plan/
  ACTIVE              # one line: slug of the plan being planned or run (absent when idle)
  <slug>.md           # the plan (from templates/PLAN.md or templates/PLAN-team.md)
  <slug>.state.json   # workflow tier (optional in team): run record, written only by the CLI
docs/refs/            # reference pack, if the repo has one: INDEX.md, manifest.json, *.md
```

Plan front matter carries `status`: `planning` → `approved` → `running` →
`done` (or `abandoned`), and `review`: `pending` → `passed` or `waived`. Task
lines use `- [ ]` open, `- [x]` done, `- [!]` blocked. The optional hooks read
exactly these. The full grammar and every check code are in
`references/plan-format.md`.

## Tiers

Choose the tier when the plan starts:

| Tier | When | Template |
| --- | --- | --- |
| base | always: every new plan is at least base | `templates/PLAN.md` |
| team | the session runs a dev-team workflow (`agentic-dev-team`, `openai-dev-team`, or any setup with orchestrator, writer, tester and reviewer roles and one writer per path), or the user asks for per-node assignment | `templates/PLAN-team.md` |
| workflow | only when the user asks for a workflow-shaped plan or a structured state record | `templates/PLAN-team.md` with `tier: workflow` |

Every tier gets plan review and mandatory scenarios. Team adds a DAG of nodes
in waves, each owned by a role from `## Team`. Workflow adds self-contained
node briefs and `plan/<slug>.state.json`. A plan without `tier:` is a legacy
plan and keeps working as before.

## CLI

`scripts/plan_loop.py` checks plans and records progress (Python 3.9+,
standard library only). Run it as
`python3 <skill-dir>/scripts/plan_loop.py [--cwd DIR] [--plan PATH] [--json] <command> …`,
where `<skill-dir>` is the directory holding this file. Without `--plan` it
finds `plan/ACTIVE` by walking up from `--cwd` (default: the current
directory), stopping at the `.git` root.

- `check [--phase draft|approve|run|finish]`: parse and check; the phase follows `status:` when omitted.
- `status`: status, requirements, scenarios, nodes, waves, ready and unreachable nodes, state drift.
- `digest [--short]`: the review digest.
- `waves`, `brief <ID>` (team, workflow): the minimum-depth wave layout; a node's delegation brief.
- `advance approved|running|done|abandoned [--by WHO]`: check the gate, then set `status:`.
- `node start|claim|done|fail|block|reset <ID> …`: node transitions (`references/team-workflow.md`).
- `scenario record <AT-ID> PASS|FAIL|BLOCKED --evidence TEXT [--candidate ID] [--blocker TEXT] [--by WHO]`: write an execution record row.
- `sync`: create or rebuild the state document.
- `guard`, `stop`: decisions for the hooks and the extension; always JSON, always exit 0.

Exit codes: `0` success. `1` check errors or an unmet gate, including
`advance` from the wrong status. `2` usage or I/O error, no active plan, or a
command the plan's tier does not support; `status` without an active plan
exits 0 and says so. `3` the state document is missing or out of step with the
plan (`status` and `check` in the run and finish phases; `sync` fixes it). `4`
a refused node transition. A refused command changes no file. Something other
than a regular file at the state document path makes every changing command
except `advance abandoned` refuse with exit 2 (`status` shows drift
`invalid`); abandoning still sets the status, deletes `plan/ACTIVE`, and leaves
that path as it is. A write that fails part way puts back the files already
written.

`advance` gates: `approved` only from planning, when `check --phase approve`
has no error (the review gate included); it writes `status: approved` and
`review: passed`, or `waived` when a waiver line exists. `running` only from
approved. `done` only from running, when `check --phase finish` has no error:
no `[ ]` or `[!]` node, every scenario PASS, no stale done node; it ticks every
requirement whose scenarios all PASS and deletes `plan/ACTIVE`. `abandoned`
always; it deletes `plan/ACTIVE`. Advancing to the current status changes
nothing.

## Mode: plan

Read-only except `plan/`. Do not edit source, install packages, run
migrations, commit, or start long-lived services. Builds or tests may run only
to observe current behavior.

Timebox: 30 minutes of drafting for a feature-sized task. If the plan is still
growing at the limit, cut scope into `Won't` instead of extending the timebox.
Review has its own budget of at most three rounds.

1. **Start.** Pick a short kebab-case slug and the tier. Write `plan/ACTIVE` with the slug and create `plan/<slug>.md` from the tier's template with `status: planning` and `review: pending`; set `slug`, `created`, `team` (team, workflow) and `state: plan/<slug>.state.json` (workflow only). The templates hold example values and `<…>` placeholders; replace or delete every one.
2. **Request.** Copy the user's request verbatim into `## Request`, with every confirmed decision: an ID, the decision, and how it was confirmed. Add each new decision as the user makes it. Reviewers compare the plan against this section.
3. **Read before deciding.** Repository instructions (`AGENTS.md`, README), the code paths the change touches, existing tests, and conventions. Reuse existing patterns; do not plan a second convention.
4. **Goal and acceptance.** One-line goal, non-goals (`Won't`), and requirements in `## Acceptance criteria`: one `- [ ] A1 …` line each, with a stable ID, phrased as an observable result: a command and its expected output, a request and its response, a UI state reached by a click path.
5. **References (reference-pack aware).** For every library or framework the tasks will touch:
   - If `docs/refs/INDEX.md` exists, find the matching topic file and list it. Check its `project_version` against the version actually declared in the build file (`package.json`, `build.gradle.kts`, …). Note any mismatch in the plan; never silently use docs for another major.
   - If the topic is missing, query Context7 using the pinned ID from `INDEX.md` (skip library resolution). If the library is not in the pack at all, resolve it once, prefer the official source and a version-pinned ID, and list the ID plus the query.
   - Propose `docs/refs/manifest.json` additions for anything fetched ad hoc, so `run` can persist them with the repo's `scripts/fetch-refs.mjs`.
   - Every task that calls a library API names the reference it relies on.
6. **Contracts.** Interfaces shared between tasks or between agents: endpoints and DTO names, schemas, function signatures, file formats. Contracts are binding during `run`.
7. **Scenarios.** Define which tests must pass, not the test code. Each requirement gets at least one happy-path scenario, plus failure, boundary, authorization, and persistence checks where the feature has those risks; a category that does not apply gets its reason in the coverage table. Each scenario is a `### AT-NN — title` block with the seven fields Requirement, Preconditions / data, Actions, Expected outcome, Verification, Owners, Evidence required, exact enough that two executors reach the same verdict. The execution record starts with every scenario `NOT_RUN`.
8. **Tasks.**
   - Base: ordered tasks in `### Phase N` groups. Each task is one bounded change with an ID (`T1`), the files it touches (code and its tests), the reference(s) it uses, the scenarios it serves, and a check that proves it. A walking skeleton (one thin end-to-end path) comes first when the work spans layers.
   - Team: fill `## Team` from the role tables in `references/team-workflow.md`, then nodes in `### Wave N` with `owner`, `after`, `writes`, `scenarios`, `check`, `refs`. One writer per path; nodes in one wave never share write paths; after the last work wave come a test gate (`scenarios: all`) and a review gate. Compare your layout with `waves`.
   - Workflow: also `## Workflow` (`max-parallel`, `max-attempts`) and `consumes`, `produces`, `done-when` on every work node, so that `brief <ID>` is a complete delegation.
   - No task may say "investigate" or "decide"; resolve those now or move them to `Risks and open questions`.
9. **Verification.** The full commands (build, lint, typecheck, tests) and one end-to-end smoke scenario that exercises the changed path for real.
10. **Risks and open questions.** Only items that change the plan. Each open question gets a recommended answer.
11. **Machine check.** Run `check --phase draft` and fix the plan until it reports no error.
12. **Plan review.** Before the user sees the plan, a reviewer who did not write it reviews it in a fresh context, following `references/plan-review.md`: blocking findings only under B1–B6, the smallest fix per finding, at most three rounds, each round recorded in `## Plan review` with the digest from `digest --short`. If three rounds pass without PASS, or a round leaves the same open findings as the one before, stop and ask the user: fix, waive, or abandon.
13. **Stop for approval.** Show the plan path and a short summary: goal, phases or waves, riskiest task, references with version mismatches, open questions, and the review result (verdict, rounds, rejected or open findings; "self review" if it was one). Ask for approval and wait. If the user asks for changes, make them and run one more round on the changed parts, or record the user's waiver (`- Waived by user: YYYY-MM-DD — reason`).
14. **Approve.** Run `advance approved`. Do not start `run` until it succeeds.

## Mode: run

1. **Load.** Read `plan/ACTIVE` and the plan. Refuse to run a plan whose status is not `approved` or `running`. Run `advance running`, then `check`; fix every error it reports before executing (exit 3: run `sync`).
2. **Mirror progress.** Put the current phase's tasks or the active wave's nodes into `update_plan` (Codex) or `todo` (omp): exactly one `in_progress` per worker, each marked done the moment its check passes. The plan file is the durable record; the tool list is the live view.
3. **Execute by tier.**
   - Base: one task at a time, in order, with the loop below.
   - Team: wave by wave, as in `references/team-workflow.md` section 4. Delegate each node of the active wave with its `brief <ID>` output to its owner's host agent. A wave is a barrier. With one writer in the wave, the writer runs its own check; with two or more, nobody builds or tests while they write and the orchestrator runs every node's check when the wave closes.
   - Workflow: the protocol in `references/team-workflow.md` section 5: `node start`, `brief`, delegate up to `max-parallel` nodes, `node claim` with the executor's agent, provider, model, and effort, wave-close checks with no writer active, then `node done --by <confirmer>` or `node fail`.
4. **Loop per task.** For each task or node:
   1. Read the references listed for it before writing code that uses those APIs.
   2. Implement the smallest complete change. No stubs, placeholders, `TODO: implement`, or mock fallbacks presented as real behavior.
   3. Run its check when the concurrency rule allows it. If the check fails, fix and rerun; do not weaken or skip the check.
   4. Record it. The orchestrator (the session itself in a base plan) runs `node done <ID> --evidence "<command> → <observed result>"`, which ticks the box and appends the evidence line; a workflow node is claimed first and needs `--by <confirmer>`. For delegated work, the evidence also names the role and the provider, model, and effort shown in the host's runtime metadata.
5. **Blocked work.** `node block <ID> --reason "<reason and what would unblock it>"` marks `- [!]`. Continue with tasks that do not depend on it. When only blocked work remains, stop and report it.
6. **Scenarios.** When implementation is complete, freeze a candidate (an identifier and its changed-file set) and run every scenario on it, exactly as written; in team plans the test gate's executor does this. Record each result with `scenario record AT-NN PASS|FAIL|BLOCKED --evidence "<observed result>" --candidate <id>`; only the orchestrator records, from the executor's report. A FAIL goes back to the owner of the path; the fix makes a new candidate and the affected scenarios run again.
7. **Plan changes.** New work discovered mid-run goes under `## Changes` with its reason before it is done; team plans add a fix wave with new test and review gates. A change to a contract, scope, acceptance criterion, or expected outcome needs the user's confirmation first; scenario IDs stay stable. With a state document, run `sync` after editing node definitions and `node reset <ID> --cascade` for stale nodes. Persist newly needed references by adding manifest entries and running `node scripts/fetch-refs.mjs --only <topic>` when the repo has that script.
8. **Finish.** Run the full verification and the smoke scenario. Record commands and results under `## Verification`. Every scenario needs PASS evidence; FAIL, BLOCKED, or NOT_RUN is not done. Run `advance done` and report what now works and how to try it.

Do not end a turn while an unblocked task is open, or while a scenario is still
NOT_RUN after every task is done, except to ask a question only the user can
answer. Never commit, push, deploy, or change global settings unless the user
asked for it.

Legacy plans (no `tier:`) run as before: tick `- [x]` or mark `- [!]` by hand,
set `status:` by hand or with `advance`, and delete `plan/ACTIVE` when done.

## Hosts without python3

- Use the manual checklist in `references/plan-format.md` instead of `check`.
- Record review digests as `unavailable`; any edit after a review round reopens review.
- Edit by hand exactly what the CLI would write (front matter `status:` and `review:`, node marks with `evidence:` and `blocked:` lines, execution record rows, the `Candidate:` line, requirement ticks, `plan/ACTIVE`), and only when the checklist's gate items hold.
- The workflow tier is not available: only the CLI writes the state document. Use the team tier and tell the user why.

## Hosts without subagents

- Plan review runs in self mode: one round, a fresh pass over the plan file only, with the checklist in `references/plan-review.md`. Say "self review" in the approval summary.
- Team and workflow plans run every node in this session, in file order within each wave; gates still wait for a frozen candidate. In the workflow tier the user confirms each node (`node done <ID> --by user`). Details: `references/team-workflow.md` section 7.

## Guards

The optional Codex hooks and omp extension are aids, not a sandbox. The first
control is this skill's rule: read-only except `plan/` while planning. The
guards do not see writes made through interpreters or build tools, omp `eval`,
MCP tools, or other extensions' tools, and they do not enforce per-node write
scopes during run. Their exact scope: `references/team-workflow.md` section 8.

## Delegation

For multi-agent runs, use the team tier: the plan's Contracts and nodes become
the worker briefs (`brief <ID>`), one owner per path, each brief cites its
references and scenarios, and the orchestrator alone edits the plan file and
records results. Combine with `agentic-dev-team` or `openai-dev-team` (roles
and models) or `hackathon-plan` (30-minute contest timebox), which use the same
contract-first structure.

## Optional Codex hooks

`codex/plan-loop/` in the lstack repository ships two hooks and an installer:

- `plan_guard.py` (PreToolUse): while the active plan is `planning`, denies `apply_patch` edits outside `plan/` and obviously mutating shell commands.
- `stop_guard.py` (Stop): while the active plan is `running`, blocks the stop and tells Codex what is next: the next open `- [ ]` task in a legacy plan; in a tier plan, the next ready node and its owner, or the scenarios still NOT_RUN once every node is done. It allows the stop when the remaining nodes wait on blocked nodes, and gives up after 5 consecutive continuations without progress (a newly done task or node, or a newly recorded scenario), so a stuck loop ends.

Install with `python3 codex/plan-loop/install.py` from the lstack checkout. It
prints the planned changes; `--apply` symlinks the skill into
`~/.agents/skills/` and appends both handlers to `~/.codex/hooks.json` after
writing a backup. Existing hooks are left untouched. The hooks load this
skill's `scripts/` from the same checkout, so keep the skill installed as that
symlink rather than a copy.

## Optional omp extension

The lstack repository also ships an omp extension. From the checkout,
`python3 omp/plan-loop/install.py` prints the planned links; `--apply`
symlinks the extension and this skill into the omp agent directory
(`$PI_CODING_AGENT_DIR`, default `~/.omp/agent`; `--agent-dir` picks another)
and leaves existing entries untouched. Restart omp afterwards. The extension
adds the planning write guard and the stop guard, a `plan_loop` tool that runs
the CLI's `check`, `status`, `digest`, `waves`, `brief`, `sync`, `advance`,
`node` and `scenario` (subagents may run only the first five), and the
`/plan-loop` command: `status` prints a one-line summary without a model turn,
or `plan-loop: unavailable (<reason>)` as a warning when the CLI is missing,
fails, or exits non-zero (exit 3 when the state document is missing or out of
step, for example); `plan <request>` and `run` turn off built-in plan mode and
start this skill. When the CLI is missing, exits non-zero, or does not answer
within 5 seconds, both guards allow and warn once per session.
