# Team and workflow plans

How team and workflow plans assign work, run it wave by wave, and record it;
how each host delegates; and what the optional guards do and do not cover. The
grammar is in `references/plan-format.md`. The plan file never names an
execution mechanism: section 7 maps each step to the host.

## 1. Kinds

Checks look only at a role's Kind. Role names and host agent names are values
in the `## Team` table.

| Kind | How many | Owns | Does |
| --- | --- | --- | --- |
| orchestrator | exactly one | `plan/`, shared files (interfaces, lockfiles, generated files), any work node that touches them | Delegates, integrates, closes waves, freezes the candidate, records every result. The only role that edits the plan and runs `advance`, `node`, `scenario` and `sync`. |
| writer | any | work nodes | Writes a node's code and its tests inside the node's `writes`. Runs its own `check` only when it is the only writer in the wave. |
| executor | at least one | `gate: test` nodes; the executor in scenario `Owners` | Runs scenarios on the frozen candidate exactly as written and reports PASS, FAIL or BLOCKED with evidence. Edits nothing. |
| reviewer | at least one | `gate: review` nodes; the plan review | Read-only review. |

## 2. Role tables

Copy the table for the team in use into `## Team` and set the front matter
`team:` key to its name.

### agentic-dev-team

`team: agentic-dev-team`

| Role | Kind | Host agent | Notes |
| --- | --- | --- | --- |
| `main` | orchestrator | Main session | consent gate, `plan/`, shared files, integration, wave close |
| `backend-implementer` | writer | `backend-implementer` | assigned non-UI production slice and its tests |
| `ui-designer` | writer | `ui-designer` | UI slice and its tests |
| `testcode-writer` | writer | `testcode-writer` | test-only nodes (section 3): cross-slice integration and end-to-end tests, shared fixtures and helpers, regression tests |
| `tester` | executor | `tester` | acceptance scenarios on the frozen candidate; edits nothing |
| `reviewer` | reviewer | `reviewer` | plan review and final review; read-only |

- `architect` works in plan mode, before or while the plan is written, and owns
  no node. It has no row because a row needs one of the four Kinds.
- A work node's owner writes the slice's code and its tests together, whatever
  the role. `testcode-writer` owns only test-only nodes (section 3), never the
  tests of a slice another writer implements.
- List only the roles the plan uses.

### openai-dev-team

`team: openai-dev-team`

| Role | Kind | Host agent | Notes |
| --- | --- | --- | --- |
| `orchestrator` | orchestrator | this session, Orchestrator route | scope, contracts, `plan/`, integration, wave close |
| `backend-implementer` | writer | subagent, Implementer route | backend slice code and its tests |
| `frontend-implementer` | writer | subagent, Implementer route | frontend slice code and its tests |
| `tester` | executor | subagent, Tester route | builds, tests and scenarios on the stable candidate; edits nothing |
| `reviewer` | reviewer | subagent, Reviewer route | read-only review |

- Model routes, efforts and fallbacks are defined by the `openai-dev-team`
  skill. A single-slice plan uses one `implementer` row instead of the two
  implementer rows.

### generic

`team: generic`, for any team or none.

| Role | Kind | Host agent | Notes |
| --- | --- | --- | --- |
| `main` | orchestrator | this session | owns `plan/` and shared files, delegates, records results |
| `implementer` | writer | default subagent | writes a node's code and its tests |
| `tester` | executor | default subagent | runs scenarios on the frozen candidate, edits nothing |
| `reviewer` | reviewer | default subagent | read-only plan review and final review |

## 3. Team rules

| Rule | Check code |
| --- | --- |
| A work node has `owner`, `after`, `writes` and `scenarios`; its owner's Kind is writer, or orchestrator for shared files. | `E-NODE-FIELD`, `E-TEAM-ROLE`, `E-NODE-KIND` |
| A work node's `writes` holds its code and the tests for that code. | allowed by the format |
| Every scenario is listed by at least one work node. | `E-SCEN-UNCLAIMED` |
| Nodes in the same wave do not write overlapping paths. | `E-SCOPE-OVERLAP` |
| Nodes in different waves may write overlapping paths only with the same owner: one writer per path. | `E-SCOPE-OWNER` |
| Only the orchestrator writes under `plan/`. | `E-SCOPE-PLAN` |
| `after` names known nodes, has no cycle, and points only to earlier waves. | `E-DAG-UNKNOWN`, `E-DAG-CYCLE`, `E-WAVE-ORDER`, `E-WAVE-MISSING` |
| A `gate: test` owner has Kind executor, a `gate: review` owner has Kind reviewer, and a gate has `writes: —`. | `E-GATE-OWNER`, `E-GATE-WRITES` |
| A wave with a gate holds only gates: gates start after the candidate is frozen, never during writing. | `E-GATE-WAVE` |
| After the last work wave comes a `gate: test` node with `scenarios: all`, and after it a `gate: review` node. | `E-GATE-FINAL-TEST`, `E-GATE-FINAL-REVIEW` |
| A scenario's executor has Kind executor. | `E-SCEN-EXECUTOR` |

- **Waves are barriers.** Wave k+1 starts only after every node of the earlier
  waves is done, blocked, or unreachable (behind a blocked node) and the
  wave-close checks have passed. `node start` enforces the first part (exit 4).
- **No builds during concurrent writing.** A node's `check:` is run by its owner
  only when that owner is the only writer in the wave. With two or more
  writers, nobody builds, tests, lints or formats while they write; the
  orchestrator (or an executor) runs every node's `check:` when the wave closes.
- **Test-only nodes** are for integration or end-to-end tests across several
  writers' slices, fixtures or helpers shared by two or more nodes, and
  regression tests for existing code that no work node touches. Their owner is
  a writer (`testcode-writer` in agentic-dev-team). If the interface they test
  is not fixed in `## Contracts`, put them `after` the nodes that build it.
- **Wave layout.** `waves` prints the minimum-depth layout: a node's level is
  one more than the highest level in its `after` (1 without `after`); of two
  nodes on one level with overlapping `writes`, the later one in the file moves
  down a level; a gate sharing a level with a work node moves down a level;
  order inside a wave is file order. `matchesDeclared` says whether the plan's
  `### Wave N` layout is the same. A different declared layout is allowed when
  it passes `check`.

## 4. Running a team plan

1. **See the wave.** `status` shows ready nodes (pending, with every `after`
   done), unreachable nodes (behind a blocked node), and the active wave: the
   first wave holding a node that is not done, blocked, or unreachable, the
   same barrier `node start` applies. There is no active wave when every node is
   done, blocked, or unreachable. A wave shows `closed` only when all its nodes
   are done or blocked; other waves show `active` or `pending`.
2. **Delegate.** For each node of the active wave, render `brief <ID>` and send
   the output to the Host agent of the node's owner (section 7). Add the
   candidate identifier and any host-specific context alongside it. The brief
   contains the Goal, the whole `## Contracts` section, the node's fields, the
   build-and-test rule for the wave, the full text of the node's scenarios and
   their requirements, the forbidden paths, and the report format.
3. **Forbidden paths** in a brief are the other nodes' `writes` patterns that do
   not overlap this node's `writes`, plus `plan/` unless this node writes there.
   A later node of the same owner that legitimately writes the same paths is
   therefore not blocked.
4. **Take results.** Check the actual changed files, untracked ones included,
   against the node's `writes`. Send scope violations and failures back to the
   same owner. When the wave closes with two or more writers, run every node's
   `check:` yourself.
5. **Record.** `node done <ID> --evidence "<text>"` marks `[x]` and appends an
   `evidence:` line. Name the role, the provider, model and effort shown in the
   host's runtime metadata, the changed files, and the check with its result.
   A node that cannot proceed: `node block <ID> --reason "<text>"` (marks `[!]`,
   writes the reason on an indented `blocked:` field line); nodes behind it
   become unreachable, independent nodes go on.
6. **Freeze and gate.** After the last work wave, name the candidate: an
   identifier and its actual changed-file set. The test gate's executor runs
   every scenario on that candidate without changing it. Record each result
   with `scenario record <AT-ID> PASS|FAIL|BLOCKED --evidence "<text>"
   --candidate <id>`, then `node done <test gate>`; it is refused while one of
   its scenarios is still NOT_RUN. The reviewer gets the Request, the
   scenarios, the contracts, the actual diff including new files, and the
   executor's evidence. Then `node done <review gate>`.
7. **Fix loop.** A FAIL, BLOCKED or review finding closes the gate anyway; the
   gate stays `[x]`. Append a new wave of fix nodes owned by the writers of the
   affected paths, then a new test gate with `scenarios: all`, then a new
   review gate, and note the reason under `## Changes`. Fixes produce a new
   candidate identifier. Scenario IDs never change; expected outcomes change
   only with the user's approval.

## 5. Workflow tier

Everything in sections 3 and 4 applies. The workflow tier adds:

- **Self-contained briefs.** Every work node has `consumes`, `produces`,
  `done-when` and `check`. The orchestrator sends the `brief <ID>` output as the
  delegation text.
- **Data passes through files only.** `produces` lies inside the node's own
  `writes`. `consumes` is produced by an ancestor node or already exists in the
  repository. A node whose inputs are missing when it starts fails
  (`node fail`).
- **Policy.** `## Workflow` sets `max-parallel` (nodes delegated at once) and
  `max-attempts` (default 2).
- **State document.** `plan/<slug>.state.json` (section 5.3) is required.

### 5.1 Execution protocol

1. `status`: find the active wave and its ready nodes.
2. For each ready node, at most `max-parallel` at a time:
   `node start <ID> --by <orchestrator>`, then delegate with the `brief <ID>`
   output.
3. When a result arrives: `node claim <ID> --agent <agent> --provider <provider>
   --model <model> --effort <effort> --evidence "<changed files>"`, with the
   values from the host's runtime metadata.
4. When every node of the wave is claimed or failed and no writer is active,
   the orchestrator or an executor runs each node's `check:` and confirms its
   `done-when`.
5. Pass: `node done <ID> --by <confirmer> --evidence "<check> → <result>"`.
   Fail: `node fail <ID> --reason "<text>"`, then delegate again.
6. When every node of the wave is done, blocked, or unreachable, go on to the
   next wave.

The confirmer must differ from the agent that claimed the node: a node is never
done on its owner's word alone. A workflow claim without a non-empty `--agent`
is refused with exit 2. A `done` on a work node that is not claimed, was
claimed without an agent, has no `--by`, or names the claimant in `--by` is
refused with exit 4. Gates follow the team rules and need no claim.

### 5.2 Failure and change

- `node fail` adds one attempt and returns the node to pending. At
  `max-attempts` it becomes blocked: `[!]` with a `blocked:` field line, as
  `node block` writes it. Nodes that depend on it cannot start and `status`
  lists them as unreachable; later waves that do not depend on it proceed.
- A definition change (scope, contract, expected outcome) needs the user's
  confirmation and a `## Changes` entry. After approval, `sync` marks each
  changed node and everything downstream as stale and raises the plan revision.
  Run `node reset <ID> --cascade` and execute the nodes again. A done node that
  is still stale blocks `advance done` (`E-STATE-NODE-STALE`).

### 5.3 State document

- Path `plan/<slug>.state.json`, schema `schemas/plan-state.schema.json`
  (`schemaVersion: 1`, with `nodes`, `edges` and `waves` for later viewers).
  Required in the workflow tier, optional in the team tier.
- The plan markdown is the source for definitions and completion marks. The
  JSON alone holds the run record: attempts, timestamps, running and claimed
  states, the executor's agent, provider, model and effort, and events. Only
  the CLI writes it; never edit it by hand.
- `advance`, `node` and `scenario` update it at the end of every successful
  command. `sync` creates it or rebuilds it from the plan.
- If the plan was edited by hand, `status` and `check` exit 3 (`E-STATE-STALE`)
  in the run and finish phases; `sync` reconciles, the markdown wins, and nodes
  ticked by hand are recorded as `reconciled` events. Changing commands
  reconcile on their own before they validate.
- A missing state document is `E-STATE-MISSING` (exit 3). A broken one makes
  `status` report `drift: "invalid"` and `check` report `E-STATE-SCHEMA`; fix
  it or delete it and run `sync`. Something other than a regular file at the
  state document path (a directory, for example) also shows as
  `drift: "invalid"`, and every changing command except `advance abandoned`
  refuses with exit 2 until it is moved away. `advance abandoned` always goes
  through: with a broken state document, or something other than a regular
  file at its path, it sets the status, deletes `plan/ACTIVE`, and leaves the
  state document path as it is.

## 6. Node transitions

| Command | Needs | Effect | Refused |
| --- | --- | --- | --- |
| `node start <ID> [--by]` | state document | pending to running | not pending; an `after` node not done; an earlier wave still holds a node that is not done, blocked, or unreachable; a gate while any node is running or claimed (exit 4). No state document (exit 2). |
| `node claim <ID> --agent --provider --model --effort [--evidence]` | state document; workflow: a non-empty `--agent` | running to claimed; records the executor | not running (exit 4); workflow without `--agent` (exit 2). A team plan may claim without an agent. |
| `node done <ID> [--by] [--evidence]` | — | to done; marks `[x]`, adds `evidence:` | blocked; team and workflow: an `after` node not done; a test gate with a NOT_RUN scenario; workflow work node: not claimed, claimed without an agent, no `--by`, or `--by` equal to the claimant (exit 4) |
| `node fail <ID> [--reason]` | state document | running or claimed to pending, attempt plus one; blocked at `max-attempts`, with the reason (or the attempt count) on the `blocked:` field line | any other state (exit 4) |
| `node block <ID> --reason` | — | to blocked; marks `[!]` and writes the reason on one indented `  - blocked: <reason>` field line, replacing an earlier `blocked:` line and dropping an inline ` — blocked:` part from the head line | no `--reason` (exit 2); done (exit 4) |
| `node reset <ID> [--cascade]` | — | done or blocked to pending; removes every `blocked:` field line and inline part; clears stale flags; `--cascade` includes every dependent | running or claimed (exit 4; use `node fail`) |

- Repeating a transition into the state a node already has exits 0 and changes
  nothing.
- Values must be one line; `scenario record` needs a non-empty `--evidence`,
  and its values must not contain `|` (exit 2). A scenario without an
  execution record row is refused with `E-RECORD` (exit 1).
- Refused commands (exit 1, 2 or 4) leave the plan and the state document
  untouched. A write that fails part way (exit 2) puts back the files it had
  already written; only when that also fails does the error say
  `could not restore` and name the files left changed.
- Legacy plans have no node IDs: `node`, `scenario` and `sync` exit 2.

## 7. Host mapping

| Step | omp | Codex | No subagents |
| --- | --- | --- | --- |
| Delegate a wave | one `task` call with a `tasks[]` item per node: `agent` is the role's Host agent, `task` is the `brief <ID>` output, shared `context` | ask Codex to spawn one subagent per node and wait for all of them; role agents can be custom agents in `~/.codex/agents/*.toml` or `.codex/agents/` | run the wave's nodes yourself, in file order |
| A fixed dependency whose result is needed as a value | eval `agent()` handles with `wait()`, or `workpool()` for many similar items; not when the team skill forbids spawning through eval (agentic-dev-team does) | not applicable | not applicable |
| Ask the same owner for a fix | `write agent://<id>` | instruct that subagent's thread | not applicable |
| Live progress | `todo` | `update_plan` | the host's progress list |
| Record state | the CLI from the shell, or the optional extension's `plan_loop` tool | the CLI from the shell | the CLI |

Without subagents:

- Every Host agent is this session. Run each wave's nodes in file order; with
  one writer at a time, run each node's `check:` when it is finished.
- Gates still wait for a frozen candidate. Run all scenarios as a separate
  executor pass, then review the diff and the evidence in a fresh pass from the
  files, as in a self review (`references/plan-review.md`).
- Workflow tier: the session is the claimant (`node claim <ID> --agent main …`),
  so the confirmer must be the user. Show the `check:` output and the
  `done-when` condition, ask, and on an explicit yes run
  `node done <ID> --by user`.

## 8. Guards: scope and limits

The guards are aids, not a sandbox. The first control is the skill's own rule:
read-only except `plan/` while planning. The guards act only while the active
plan's status is `planning` (writes) or `running` (stops). Nothing restricts
per-node write scopes during run.

Codex hooks (`codex/plan-loop/hooks/plan_guard.py`,
`codex/plan-loop/hooks/stop_guard.py`):

- `apply_patch` is denied when a file it adds, updates, deletes or moves to is
  outside `plan/`.
- A shell command is denied when it runs rm, mv, cp, mkdir, rmdir, touch, tee,
  chmod, chown, ln, truncate, `sed -i`, `perl -pi`, a package install or
  removal (npm, pnpm, yarn, pip), or a changing git subcommand (commit, push,
  reset, checkout, switch, merge, rebase, stash, apply, am, cherry-pick,
  restore, clean), or when it redirects output to a file outside `plan/`.
- Out of reach: writes made by interpreters and other programs
  (`python3 -c "open(...,'w')"`, build tools, editors).

Optional omp extension, while the plan is `planning`:

| Tool | Decision |
| --- | --- |
| `bash` | the same rules as the Codex shell check |
| `write` to a file path or `file://` URL | allowed inside `plan/`, denied outside; denied when no path is given |
| `write` to another `scheme://` path (`local://` and similar) | allowed without asking the CLI; not the working tree |
| `write xd://resolve` | denied: it applies staged changes whose targets are unknown |
| `write xd://reject`, `xd://propose`, `xd://report_issue` | allowed |
| `write xd://<tool>` | judged as `<tool>` from the JSON content; allowed when the content cannot be read |
| `edit` with `path` or `paths` | entries with a non-file scheme (`local://` and similar) are skipped, as for `write`; allowed when every remaining path is inside `plan/` or no path remains, denied otherwise |
| `edit` without a path whose input starts with `*** Begin Patch` (apply_patch edit mode) | judged like Codex `apply_patch`: denied when a file the patch adds, updates, deletes or moves to is outside `plan/` |
| `edit` without a path and without a patch | denied |
| `ast_edit` | allowed when every entry of `paths` is inside `plan/`; denied otherwise, including an empty `paths` and `local://` entries |
| `lsp` | read-only actions allowed (diagnostics, definition, type_definition, implementation, references, hover, symbols, status, capabilities); others denied |
| `github` | `pr_create`, `pr_checkout`, `pr_push` denied; others allowed |
| `eval`, `task`, `checkpoint`, `rewind`, `todo`, `ask`, read tools | allowed |
| MCP tools, other extensions' tools, `manage_skill`, `learn`, memory tools, `generate_image` | allowed: out of the guard's reach |

- `eval` stays allowed: the paths code writes cannot be known in advance, and
  planning uses `eval` for read-only analysis. The Codex hooks cannot stop
  `python3 -c` writes either, so both hosts give the same protection.
- An `edit` with a path is judged by that path only; a move target is not seen.
  In apply_patch edit mode the patch's `*** Move to:` lines are judged too.
- A glob in `edit` or `ast_edit` paths is judged by the part before its first
  wildcard.
- A `task` child with `isolated: true` runs in another directory and may not
  find `plan/ACTIVE`.
- The extension looks for the CLI at `PLAN_LOOP_CLI`, then at
  `skills/plan-loop/scripts/plan_loop.py` in its own checkout, then in the
  installed skill (`<agent-dir>/skills/plan-loop`, then
  `~/.agents/skills/plan-loop`), and runs it with `PLAN_LOOP_PYTHON` or
  python3. When python or the CLI is missing, the CLI exits with a non-zero
  code or prints no decision, or it takes longer than 5 seconds, the write
  guard and the stop guard allow and warn once per session.

Stop guards (Codex Stop hook, and the extension's `session_stop`, which does not
fire in subagents), while the plan is `running`:

- Legacy plan: keep going while an open `- [ ]` task remains, naming the next
  one.
- Tier plan: keep going while a node is ready, naming it and its owner. When
  no node is ready and a node is blocked, allow the stop so the blocked nodes
  can be reported. When every node is done but a scenario is still NOT_RUN,
  keep going and name the scenarios.
- After `PLAN_LOOP_MAX_STALLS` (default 5) continuations in a row without
  progress, allow the stop. Progress is a newly done node or newly recorded
  scenario (legacy: a newly ticked task).
