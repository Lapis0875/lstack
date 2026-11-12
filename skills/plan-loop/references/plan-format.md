# Plan format

The grammar of `plan/<slug>.md`. `scripts/plan_loop.py` reads plans with
`scripts/planlib/planfile.py` and checks them with `scripts/planlib/checks.py`;
when python3 is available, `check` is the authority. Without python3, use the
manual checklist in section 10.

Templates: `templates/PLAN.md` (base tier) and `templates/PLAN-team.md` (team
and workflow tiers).

## 1. Tiers

| Tier | Use it when | Front matter | Adds to the plan |
| --- | --- | --- | --- |
| base | always; the default for every new plan | `tier: base`, `review:` | `## Request`, `## Scenarios`, `## Plan review`, an ID on every task |
| team | the session runs a dev-team workflow (orchestrator, writer, executor and reviewer roles with one writer per path), or the user asks for per-node assignment | `tier: team`, `team: <name>` | `## Team`, `### Wave N` headings, node fields, test and review gates |
| workflow | only when the user asks for a workflow-shaped plan or a structured state record | `tier: workflow`, `team:`, `state:` | `## Workflow`, brief fields on every work node, the state document |

- The workflow tier uses the team grammar (DAG, owner, writes). It does not
  need a particular dev-team skill; without one, use `team: generic`.
- `state:` is forbidden in base, optional in team, required in workflow. Its
  value is exactly `plan/<slug>.state.json`, where slug is the plan file name
  without `.md`.
- A plan without `tier:` is a legacy plan. Only the original task counting
  applies to it (the `status:` line and the `- [ ]` / `- [x]` lines under
  `## Tasks`), the Codex hooks behave as before, and `check` reports only
  `W-LEGACY` and `W-FM-SLUG` (plus `E-FINISH-OPEN` at the finish phase). To move a legacy plan to
  the base tier, add `tier: base` and `review: pending` to the front matter and
  the `## Request`, `## Scenarios` and `## Plan review` sections. There is no
  conversion tool.

## 2. Front matter

The first block between `---` lines, one `key: value` per line.

| Key | Value |
| --- | --- |
| `title` | free text |
| `slug` | kebab-case; must equal the file name without `.md` (`W-FM-SLUG` otherwise) |
| `status` | `planning`, `approved`, `running`, `done` or `abandoned` |
| `created` | `YYYY-MM-DD` |
| `tier` | `base`, `team` or `workflow`; absent means legacy |
| `team` | `[a-z][a-z0-9-]*`, for example `agentic-dev-team`, `openai-dev-team`, `generic`; required in team and workflow |
| `review` | `pending`, `passed` or `waived` |
| `state` | `plan/<slug>.state.json`; see section 1 |

`advance` writes `status:` and, on approval, `review:`. Edit them by hand only
when python3 is unavailable (section 10).

## 3. Sections

H2 headings, in this order:

`Request` → `Goal` → `Acceptance criteria` → `Won't` → `References` →
`Contracts` → `Scenarios` → `Team` → `Workflow` → `Tasks` → `Verification` →
`Risks and open questions` → `Plan review` → `Changes`

| Tier | Required sections |
| --- | --- |
| base | Request, Goal, Acceptance criteria, Scenarios, Tasks, Verification, Plan review |
| team | the base set plus Team |
| workflow | the team set plus Workflow |

- Names match exactly, including case. A missing required section, or a known
  name used twice, is `E-SECTION`. Other H2 headings are allowed and ignored.
- The order is recommended, not checked. One order rule is enforced by
  parsing: coverage rows are read only before the first `### AT-` heading in
  `## Scenarios`.
- `## Plan review` ends at the next H2 heading. The review digest leaves this
  section out, so recording a round does not change the digest.

What each section holds:

| Section | Content |
| --- | --- |
| Request | The user's request, verbatim, and every confirmed decision with an ID, the decision, and how it was confirmed. Reviewers compare the plan against it. |
| Goal | One sentence: what works afterwards that does not work now, and for whom. |
| Acceptance criteria | Requirements: one line each, a stable ID and what must be true. |
| Won't | Explicit non-goals. |
| References | Docs the tasks rely on, pinned to versions (see SKILL.md, plan mode). |
| Contracts | Interfaces shared between tasks or agents. Binding during run. |
| Scenarios | Coverage table, one block per scenario, and the execution record. Scenarios are the proof procedure for the requirements; they say what to test, not the test code. |
| Team | Role table (team and workflow). |
| Workflow | Execution policy (workflow). |
| Tasks | Base: tasks, optionally grouped in `### Phase N`. Team and workflow: nodes in `### Wave N`. |
| Verification | Build, test and smoke commands; results are filled during run. |
| Risks and open questions | Only items that change the plan, each with a recommended answer. |
| Plan review | Review rounds, findings, or the user's waiver (`references/plan-review.md`). |
| Changes | Changes made during run, each with a reason. |

## 4. Reading rules

- A UTF-8 BOM is dropped and `\r\n` or a lone `\r` is read as `\n` before
  parsing. CLI edits keep the file's line ends.
- Tier plans skip lines inside fenced code blocks. A fence opens with three or
  more backticks or tildes indented by at most three spaces and closes with the
  same character, at least as many, followed only by spaces; an unclosed fence
  runs to the end of the file. Legacy plans and earlier hook versions do not
  know fences and count checkbox lines inside them. Never put a `## ` line or a
  checkbox line inside a fenced block in a plan.
- HTML comments are not skipped. Keep grammar-shaped lines (headings, checkbox
  lines, table rows, field lines) out of comments.
- In `## Tasks`, a non-blank line that starts at column 0 ends the current
  node. Do not put a comment or prose line between a node and its fields.
- Checkbox lines in `## Tasks` start at column 0. An indented checkbox line is
  `E-TASK-INDENT`.

## 5. Line grammar

The regular expressions are what the parser matches. Text in angle brackets in
the examples is a free value.

**G1 requirement**, in `## Acceptance criteria`:

    - [ ] A1 Uploading a valid CSV creates one order per row

`^- \[( |x|X)\] ([A-Z]{1,3}\d{1,3})\s+(\S.*)$`. IDs such as `A1`, `R1`, `M1`.
`advance done` writes `[x]` when every linked scenario is PASS.

**G2 coverage row**, in `## Scenarios` before the first `### AT-` heading:

    | Requirement | Happy path | Other checks | Not applicable (reason) |
    | --- | --- | --- | --- |
    | A1 | AT-01 | AT-03 | authorization: the endpoint is internal-only |

`^\|\s*([A-Z]{1,3}\d{1,3})\b[^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$`. Scenario IDs
are taken from the cells with `AT-\d{2,3}`; `—` means none. One row per
requirement. The last column names each risk category (failure, boundary,
authorization, persistence) that does not apply, with the reason.

**G3 scenario heading**, in `## Scenarios`:

    ### AT-01 — valid file creates orders

`^### (AT-\d{2,3}) (?:—|-) (\S.*)$`.

**G4 scenario fields**, the seven lines under a G3 heading:

    - Requirement: A1
    - Preconditions / data: empty orders table; fixtures/3rows.csv
    - Actions: curl -F file=@fixtures/3rows.csv localhost:8080/api/orders/import
    - Expected outcome: 201; orders has exactly 3 rows; no other table changes
    - Verification: curl and a row count
    - Owners: implementer implementer; executor tester
    - Evidence required: response body, row count

`^- (Requirement|Preconditions / data|Actions|Expected outcome|Verification|Owners|Evidence required):\s*(.*)$`.
An indented line that follows continues the previous field. `Requirement` is a
comma list of one or more requirement IDs (`A1, A2`). `Owners` matches
`^implementer\s+([^;]+);\s*executor\s+(.+)$`; in team and workflow plans the
executor is a role whose Kind is `executor`. A base plan has no `## Team`, so
its Owners values are plain role names; `main` is the session that wrote the
plan. A field that is empty or whose whole value is one `<…>` placeholder is
`E-SCEN-FIELD`.

**G5 execution record**, a `### Execution record` block at the end of
`## Scenarios`:

    ### Execution record
    Candidate: —

    | Scenario | Status | Observed result and evidence | Blocker |
    | --- | --- | --- | --- |
    | AT-01 | NOT_RUN | — | — |

`^Candidate:\s*(.+)$` and
`^\|\s*(AT-\d{2,3})\s*\|\s*(NOT_RUN|PASS|FAIL|BLOCKED)\s*\|([^|]*)\|([^|]*)\|\s*$`.
Exactly one row per scenario, all `NOT_RUN` until the plan is approved. Only the
orchestrator writes results (with `scenario record`), from the executor's
report.

**G6 role row**, in `## Team`:

    | Role | Kind | Host agent | Notes |
    | --- | --- | --- | --- |
    | `implementer` | writer | default subagent | writes a node's code and its tests |

``^\|\s*`?([a-z][a-z0-9-]*)`?\s*\|\s*(orchestrator|writer|executor|reviewer)\s*\|([^|]*)\|([^|]*)\|\s*$``.
Checks use the Kind only; role and host agent names are values. Role tables
per team: `references/team-workflow.md`.

**G7 wave heading**, in `## Tasks`: team and workflow `^### Wave (\d+)(?:: (.+))?$`;
base, optional, `^### Phase (\d+)(?:: (.+))?$`.

**G8 node head**, in `## Tasks` at column 0:

    - [ ] N1 CSV parser with header validation

`^- \[( |x|X|!)\] ([A-Z]{1,3}\d{1,3}[a-z]?)\s+(\S.*)$`. `[ ]` open (pending,
running or claimed), `[x]` done, `[!]` blocked. Node IDs differ from
requirement IDs. Gate nodes conventionally use `G1`, `G2`.

**G9 field line**, under a G8 line, indented by two or more spaces:

      - owner: implementer

`^ {2,}- (owner|after|writes|files|scenarios|gate|refs|check|consumes|produces|done-when|evidence|blocked):\s*(.*)$`.
A field can also sit on the head line as a ` — key: value` part, which is how
earlier plans wrote tasks:

    - [ ] T1 Add the parser — files: `src/csv/parser.py` — check: `pytest tests/csv`

Values are in section 6.

**G10 execution policy**, in `## Workflow`: `^- (max-parallel|max-attempts):\s*(\d+)$`.

**G11 review round**, **G12 finding**, **G13 waiver**, in `## Plan review`:

    - Round 1 — reviewer: reviewer (provider/model, effort high) — mode: independent — digest: 1c87d6278f5f — verdict: REVISE
      - F1 [B4] AT-03 cites a command that does not exist — status: fixed (command corrected)
    - Waived by user: 2026-11-12 — the user approved without another round

- G11 `^- Round (\d+) — reviewer: (.+?) — mode: (independent|self) — digest: ([0-9a-f]{12}|unavailable) — verdict: (PASS|REVISE)$`
- G12 `^ {2,}- (F\d+) \[(B[1-6])\] (.+?) — status: (open|fixed|rejected|waived)(.*)$`
- G13 `^- Waived by user: (\d{4}-\d{2}-\d{2}) — (.+)$`

Procedure and meaning: `references/plan-review.md`.

## 6. Node fields

| Field | Value | Required |
| --- | --- | --- |
| `owner` | a role from `## Team` | team and workflow, every node |
| `after` | `—`, `-`, `none`, or node IDs (`N1, N2`) | team and workflow, every node |
| `writes` | `—` or a comma list of backticked path patterns; `files` is an alias kept for base plans | team and workflow work nodes; gates use `—` |
| `scenarios` | `—`, `all`, or scenario IDs (`AT-01, AT-02`) | team and workflow, every node |
| `gate` | `test` or `review`; absent means a work node | gates only |
| `refs` | free text naming rows of `## References` | no |
| `check` | the command or scenario that proves the node | workflow work nodes |
| `consumes` | `—` or backticked paths the node reads from upstream nodes or the repository | workflow work nodes |
| `produces` | `—` or backticked paths the node hands on; inside its own `writes` | workflow work nodes |
| `done-when` | the observable condition the confirmer checks; not `—` | workflow work nodes |
| `evidence` | free text; repeatable; added during run | no |
| `blocked` | the reason; written by `node block` and by `node fail` at the attempt limit | no |

- A key given twice on one node is `E-NODE-FIELD` (`evidence` may repeat).
- A work node's `writes` lists its code and its tests together; the same owner
  writes both.
- `scenarios: all` expands to every scenario ID. A work node with
  `scenarios: —` gets `W-NODE-NOSCEN`.

## 7. Path patterns

`writes`, `consumes` and `produces` accept three forms, relative to the
repository root:

| Form | Example |
| --- | --- |
| exact file | `src/csv/parser.py` |
| directory tree | `src/csv/` or `src/csv/**` |
| glob in the last segment only | `src/csv/*.py` |

Anything else (wildcards in a directory segment, `**` inside a name, braces,
absolute paths, `..`, backslashes) is `E-SCOPE-PATTERN`.

Two patterns overlap when: a tree contains or equals the other pattern's
directory or file; two files are the same path; a glob and a file in the same
directory match; two globs share a directory, unless both are `*.<ext>` with
different extensions.

## 8. Phases

`check --phase draft|approve|run|finish`. Without `--phase`, the phase follows
the status:

| Status | Phase |
| --- | --- |
| `planning`, `abandoned`, anything else | `draft` |
| `approved`, `running` | `run` |
| `done` | `finish` |

`approve` is never inferred: `check --phase approve` and `advance approved` use
it. `advance done` checks the `finish` phase.

## 9. Check codes

`E-` codes are errors and `W-` codes are warnings. `check` exits 1 when any
error is reported, and 3 when `E-STATE-STALE` or `E-STATE-MISSING` is among
them. Text output prints one finding per line,
`<path>:<line>: <CODE> <message>`, then a summary. `--json` prints one envelope:
`{"ok", "command", "plan", "tier", "status", "findings": [{"code", "severity", "message", "line", "node"}], "data"}`.

Tiers: L legacy, B base, T team, W workflow. Phases: D draft, A approve, R run,
F finish.

| Code | Tiers | Phases | Reported when |
| --- | --- | --- | --- |
| `W-LEGACY` | L | all | the plan has no `tier:`; no other structure check runs |
| `W-FM-SLUG` | all | all | front matter `slug` differs from the file name |
| `E-FM-KEY` | B T W | all | `status`, `tier` or `review` outside its values; `team` missing in T or W or not matching `[a-z][a-z0-9-]*`; `state` missing in W, present in B, or not `plan/<slug>.state.json` |
| `E-SECTION` | B T W | all | a required section is missing or a known section name appears twice |
| `E-REQ-NONE` | B T W | all | `## Acceptance criteria` has no G1 line |
| `E-REQ-DUP` | B T W | all | a requirement ID repeats |
| `E-SCEN-NONE` | B T W | all | no `### AT-` scenario |
| `E-SCEN-DUP` | B T W | all | a scenario ID repeats |
| `E-SCEN-FIELD` | B T W | all | one of the seven fields is missing, empty, or a whole `<…>` placeholder; `Owners` is not `implementer X; executor Y` or contains `<`; `Requirement` is not a list of requirement IDs |
| `E-SCEN-REQ` | B T W | all | a scenario names a requirement ID that does not exist |
| `E-COVERAGE-HAPPY` | B T W | all | a requirement has no coverage row or no `AT-` in its Happy path cell |
| `E-COVERAGE-MAP` | B T W | all | a row names a missing scenario or requirement, or a scenario whose `Requirement` does not include that row; a requirement has two rows; a scenario is in no row or missing from the row of a requirement it names |
| `E-RECORD` | B T W | all | no `### Execution record`; a scenario without exactly one row; a row with a bad status or for an unknown scenario |
| `E-RECORD` | B T W | D A | additionally, a row that is not `NOT_RUN` |
| `E-TASK-NONE` | B T W | all | `## Tasks` has no node |
| `E-TASK-ID` | B T W | all | a column-0 checkbox line without an ID; a repeated node ID; a node ID equal to a requirement ID |
| `E-TASK-INDENT` | B T W | all | an indented checkbox line in `## Tasks` |
| `W-TASK-VAGUE` | B T W | D A | a node title starts with investigate, decide, research, explore or tbd |
| `E-NODE-FIELD` | B T W | all | a repeated field, a value outside its grammar, a scenario ID that does not exist; in T and W also a missing `owner`, `after`, `writes` or `scenarios` on a work node, or a missing `owner`, `after` or `scenarios` on a gate |
| `E-TEAM-ROLE` | T W | all | `## Team` does not have exactly one orchestrator; a role repeats; a malformed role row; a node owner that is not in the table |
| `E-NODE-KIND` | T W | all | a work node owner whose Kind is neither writer nor orchestrator |
| `W-NODE-NOSCEN` | T W | D A | a work node with `scenarios: —` |
| `E-SCEN-UNCLAIMED` | T W | all | a scenario that no work node lists |
| `E-SCEN-EXECUTOR` | T W | all | a scenario executor that is not in `## Team` or whose Kind is not executor |
| `E-SCOPE-PATTERN` | T W | all | a path pattern outside the three forms |
| `E-SCOPE-OVERLAP` | T W | all | two nodes in one wave write overlapping paths |
| `E-SCOPE-OWNER` | T W | all | two nodes in different waves write overlapping paths with different owners |
| `E-SCOPE-PLAN` | T W | all | a node whose owner is not the orchestrator writes under `plan/` |
| `E-DAG-UNKNOWN` | T W | all | `after` names an unknown node or the node itself |
| `E-DAG-CYCLE` | T W | all | the `after` graph has a cycle |
| `E-WAVE-MISSING` | T W | all | a node outside a `### Wave N` heading; wave numbers that do not run 1, 2, 3 without gaps; an empty wave |
| `E-WAVE-ORDER` | T W | all | `after` names a node in the same or a later wave |
| `E-GATE-OWNER` | T W | all | a `gate: test` owner whose Kind is not executor, or a `gate: review` owner whose Kind is not reviewer |
| `E-GATE-WRITES` | T W | all | a gate whose `writes` is not `—` |
| `E-GATE-WAVE` | T W | all | a wave holding both gates and work nodes |
| `E-GATE-FINAL-TEST` | T W | all | no `gate: test` node with `scenarios: all` in a wave after the last work wave |
| `E-GATE-FINAL-REVIEW` | T W | all | no `gate: review` node in a wave after that test gate |
| `E-BRIEF-FIELD` | W | all | a work node without a non-empty `consumes`, `produces`, `done-when` or `check` (`—` does not count for `done-when` and `check`) |
| `E-BRIEF-PRODUCES` | W | all | a `produces` path outside the node's own `writes` |
| `E-BRIEF-CONSUMES` | W | all | a `consumes` path that no ancestor node produces and the repository does not have |
| `E-REVIEW-MISSING` | B T W | A | no review round and no waiver line |
| `E-REVIEW-VERDICT` | B T W | A | the last round's verdict is REVISE |
| `E-REVIEW-STALE` | B T W | A | the last round's digest differs from the current digest (`unavailable` excepted) |
| `E-REVIEW-OPEN` | B T W | A | a finding in any round still has `status: open` (`rejected` passes) |
| `W-REVIEW-NODIGEST` | B T W | A | the last round's digest is `unavailable` |
| `W-REVIEW-SELF` | B T W | A | the last round is `mode: self` |
| `E-REVIEW-STATE` | B T W | R F | front matter `review` is neither `passed` nor `waived` |
| `E-STATE-MISSING` | `state:` declared | R F | the state document does not exist (exit 3) |
| `E-STATE-STALE` | `state:` declared | R F | the state document was synced from different plan bytes (exit 3) |
| `E-STATE-SCHEMA` | `state:` declared | R F | the state document fails its schema or consistency checks |
| `E-STATE-NODE-STALE` | `state:` declared | R F | a done node marked stale: its definition, or an upstream node's, changed after approval; clear it with `node reset <ID> --cascade` |
| `E-FINISH-OPEN` | all | F | a `[ ]` or `[!]` node remains (legacy: an open task) |
| `E-FINISH-SCEN` | B T W | F | a scenario that is not PASS |

A waiver line (G13) skips all four `E-REVIEW-*` errors.

## 10. Manual checklist without python3

Use this list in place of `check` when the host has no python3. Read the plan
file itself, not your memory of it. Every item must hold; the code in
parentheses is the error the CLI would report.

Draft, every tier plan:

- [ ] Front matter: `status: planning`, `tier`, `review: pending`; `team` in team and workflow; `state: plan/<slug>.state.json` in workflow only; `slug` equals the file name. (`E-FM-KEY`, `W-FM-SLUG`)
- [ ] Every required section is present once, with the exact name. (`E-SECTION`)
- [ ] Each requirement is a `- [ ] ID text` line with a unique ID. (`E-REQ-NONE`, `E-REQ-DUP`)
- [ ] The coverage table has one row per requirement with an `AT-` in Happy path; every scenario it names exists and names that requirement; every scenario appears in a row. (`E-COVERAGE-HAPPY`, `E-COVERAGE-MAP`)
- [ ] Every scenario has all seven fields filled with no `<…>` placeholder; `Requirement` lists existing IDs; `Owners` reads `implementer X; executor Y`. (`E-SCEN-FIELD`, `E-SCEN-REQ`)
- [ ] `### Execution record` has a `Candidate:` line and exactly one `NOT_RUN` row per scenario. (`E-RECORD`)
- [ ] Every column-0 checkbox line in `## Tasks` has a unique ID that is not a requirement ID; no checkbox line is indented; no checkbox line or `## ` line sits inside a fenced block. (`E-TASK-ID`, `E-TASK-INDENT`)
- [ ] Field values follow section 6; no field repeats on a node. (`E-NODE-FIELD`)

Team and workflow, in addition:

- [ ] `## Team` has exactly one orchestrator; every owner is a role in it; work node owners are writers or the orchestrator; scenario executors have Kind executor. (`E-TEAM-ROLE`, `E-NODE-KIND`, `E-SCEN-EXECUTOR`)
- [ ] Every node has `owner`, `after`, `scenarios`; every work node also has `writes`. (`E-NODE-FIELD`)
- [ ] Every scenario is listed by at least one work node. (`E-SCEN-UNCLAIMED`)
- [ ] Path patterns use the three forms; nodes in one wave do not overlap; overlapping nodes in different waves share an owner; only the orchestrator writes under `plan/`. (`E-SCOPE-*`)
- [ ] Every `after` ID exists, is in an earlier wave, and the graph has no cycle; waves are numbered 1, 2, 3 without gaps and none is empty. (`E-DAG-*`, `E-WAVE-*`)
- [ ] Gates sit in waves of their own with `writes: —`; the test gate's owner is an executor, the review gate's owner a reviewer; a `gate: test` node with `scenarios: all` follows the last work wave and a `gate: review` node follows it. (`E-GATE-*`)

Workflow, in addition:

- [ ] Every work node has `consumes`, `produces`, `done-when` and `check`; `produces` lies inside its `writes`; each `consumes` path is produced by an ancestor node or already exists. (`E-BRIEF-*`)
- [ ] `## Workflow` sets `max-parallel` and `max-attempts`.

Before approval:

- [ ] The last review round is PASS with digest `unavailable`, no finding is `open`, and the plan has not changed since that round; or a `Waived by user` line exists. (`E-REVIEW-*`)
- [ ] Then set `status: approved` and `review: passed` (or `review: waived`) by hand.

Before finishing:

- [ ] No node is `[ ]` or `[!]`; every execution record row is PASS. (`E-FINISH-OPEN`, `E-FINISH-SCEN`)
- [ ] Tick every requirement whose scenarios all PASS, set `status: done`, and delete `plan/ACTIVE`.
