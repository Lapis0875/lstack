---
name: plan-loop
description: >-
  Plan-then-execute harness ported from omp's plan mode, todo tracking, and
  goal loop. `plan` mode investigates read-only and writes one approved plan
  file (plan/<slug>.md) whose References section pins official docs from the
  repository's Context7 reference pack (docs/refs/); `run` mode executes that
  plan task by task with live progress tracking, per-task verification, and a
  final smoke run, continuing until every task is done or blocked. Use when the
  user asks to plan before implementing, "계획 세우고 구현", "plan-loop",
  "plan mode", "execute the plan", or wants a long task driven to completion.
---

# plan-loop

Two modes over one file. `plan` produces `plan/<slug>.md` and stops for
approval. `run` executes an approved plan until it is done. The plan file is
the single source of truth for scope, references, tasks, and evidence; chat
history is not. Run the session in the user's language.

Works in Codex CLI and omp:

| Concern | Codex | omp |
| --- | --- | --- |
| Live progress | `update_plan` | `todo` tool |
| Approval | ask the user, wait for an explicit yes | plan mode `propose`, or ask |
| Keep going until done | `/goal`, plus the optional Stop hook in `codex/plan-loop/` | goal mode |
| Read-only planning | this skill's rules, plus the optional PreToolUse hook | plan mode |
| Docs lookup | `docs/refs/`, then Context7 MCP `query-docs` or `ctx7 docs` | same |

## Files

```
plan/
  ACTIVE          # one line: slug of the plan being planned or run (absent when idle)
  <slug>.md       # the plan (from templates/PLAN.md)
docs/refs/        # reference pack, if the repo has one: INDEX.md, manifest.json, *.md
```

Plan front matter carries `status`: `planning` → `approved` → `running` →
`done` (or `abandoned`). Task lines use `- [ ]` open, `- [x]` done, `- [!]`
blocked (reason on the same line). The optional hooks read exactly these.

## Mode: plan

Read-only except `plan/`. Do not edit source, install packages, run
migrations, commit, or start long-lived services. Builds or tests may run only
to observe current behavior.

Timebox: 30 minutes for a feature-sized task. If the plan is still growing at
the limit, cut scope into `Won't` instead of extending the timebox.

1. **Start.** Pick a short kebab-case slug. Write `plan/ACTIVE` with the slug and create `plan/<slug>.md` from `templates/PLAN.md` with `status: planning`.
2. **Read before deciding.** Repository instructions (`AGENTS.md`, README), the code paths the change touches, existing tests, and conventions. Reuse existing patterns; do not plan a second convention.
3. **Goal and acceptance.** One-line goal, non-goals (`Won't`), and acceptance criteria phrased as observable results: a command and its expected output, a request and its response, a UI state reached by a click path.
4. **References (reference-pack aware).** For every library or framework the tasks will touch:
   - If `docs/refs/INDEX.md` exists, find the matching topic file and list it. Check its `project_version` against the version actually declared in the build file (`package.json`, `build.gradle.kts`, …). Note any mismatch in the plan; never silently use docs for another major.
   - If the topic is missing, query Context7 using the pinned ID from `INDEX.md` (skip library resolution). If the library is not in the pack at all, resolve it once, prefer the official source and a version-pinned ID, and list the ID plus the query.
   - Propose `docs/refs/manifest.json` additions for anything fetched ad hoc, so `run` can persist them with the repo's `scripts/fetch-refs.mjs`.
   - Every task that calls a library API names the reference it relies on.
5. **Contracts.** Interfaces shared between tasks or between agents: endpoints and DTO names, schemas, function signatures, file formats. Contracts are binding during `run`.
6. **Tasks.** Ordered, grouped into phases. Each task is one bounded change with: the files it touches, the reference(s) it uses, and a check that proves it (command or scenario). A walking skeleton (one thin end-to-end path) comes first when the work spans layers. No task may say "investigate" or "decide"; resolve those now or move them to `Open questions`.
7. **Verification.** The full commands (build, lint, typecheck, tests) and one end-to-end smoke scenario that exercises the changed path for real.
8. **Risks and open questions.** Only items that change the plan. Each open question gets a recommended answer.
9. **Stop for approval.** Show the plan path and a five-line summary (goal, phases, riskiest task, references with version mismatches, open questions). Ask for approval. Do not start `run` until the user approves; then set `status: approved`.

## Mode: run

1. **Load.** Read `plan/ACTIVE` and the plan. Refuse to run a plan whose status is not `approved` or `running`. Set `status: running`.
2. **Mirror progress.** Put the current phase's tasks into `update_plan` (Codex) or `todo` (omp): exactly one `in_progress`, mark each done the moment its check passes. The plan file checkboxes are the durable record; the tool list is the live view.
3. **Loop per task.**
   1. Read the references listed for the task before writing code that uses those APIs.
   2. Implement the smallest complete change. No stubs, placeholders, `TODO: implement`, or mock fallbacks presented as real behavior.
   3. Run the task's check. If it fails, fix and rerun; do not weaken or skip the check.
   4. Tick the box and append one evidence line under the task: the command run and the observed result.
4. **Blocked tasks.** Mark `- [!]` with the reason and what would unblock it, then continue with tasks that do not depend on it. When only blocked tasks remain, stop and report them.
5. **Plan changes.** New work discovered mid-run goes under `## Changes` with its reason before it is done. A change to a contract, scope, or acceptance criterion needs the user's confirmation first. Persist newly needed references by adding manifest entries and running `node scripts/fetch-refs.mjs --only <topic>` when the repo has that script.
6. **Finish.** Run the full verification and the smoke scenario. Record commands and results under `## Verification`. Every acceptance criterion needs observed evidence; unexecuted or inconclusive is not done. Set `status: done`, delete `plan/ACTIVE`, and report what now works and how to try it.

Do not end a turn while an unblocked task is open, except to ask a question
only the user can answer. Never commit, push, deploy, or change global
settings unless the user asked for it.

## Delegation

Optional. For multi-agent runs, the plan's Contracts and Tasks become the
worker briefs: one owner per path, each brief cites its references, and the
orchestrator alone edits the plan file. Combine with `openai-dev-team` (roles
and models) or `hackathon-plan` (30-minute contest timebox), which use the same
contract-first structure.

## Optional Codex hooks

`codex/plan-loop/` in the lstack repository ships two hooks and an installer:

- `plan_guard.py` (PreToolUse): while the active plan is `planning`, denies `apply_patch` edits outside `plan/` and obviously mutating shell commands.
- `stop_guard.py` (Stop): while the active plan is `running` with open `- [ ]` tasks, blocks the stop and tells Codex which task is next. It gives up after 5 consecutive continuations without a newly ticked task, so a stuck loop ends.

Install with `python3 codex/plan-loop/install.py` from the lstack checkout. It prints the planned changes; `--apply` symlinks the skill into `~/.agents/skills/` and appends both handlers to `~/.codex/hooks.json` after writing a backup. Existing hooks are left untouched.
