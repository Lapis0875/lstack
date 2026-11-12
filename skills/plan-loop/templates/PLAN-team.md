---
title: CSV import
slug: csv-import
status: planning
created: 2026-11-12
tier: team
team: generic
review: pending
---

# CSV import

<!--
Team tier as written. Role tables for agentic-dev-team, openai-dev-team and generic teams
are in references/team-workflow.md; set the team: key to match the table you use.
Workflow tier (only when the user asks for it): set tier: workflow, add the line
state: plan/<slug>.state.json after the review: line, and keep the Workflow section and the
consumes, produces and done-when fields of every work node.
Team tier: delete the Workflow section and those three fields.
-->

## Request
> <The user's request, verbatim.>

| ID | Decision | Confirmed |
| --- | --- | --- |
| D1 | <decision the user confirmed> | <date and how it was confirmed> |

## Goal
<One sentence: what works after this plan that does not work now, and for whom.>

## Acceptance criteria
- [ ] A1 <observable result: command → expected output, request → response, click path → visible state>
- [ ] A2 <observable result>

## Won't
- <explicitly out of scope>

## References
Docs this plan relies on. Prefer `docs/refs/` files; otherwise a pinned Context7 ID and the query used.

| Topic | Source (`docs/refs/…` or Context7 ID + query) | Docs version | Project version | Used by |
| --- | --- | --- | --- | --- |
| <e.g. Python csv module> | `docs/refs/python/csv.md` | 3.12 | 3.12 | N1 |
| <e.g. Starlette file uploads> | `/encode/starlette` "UploadFile multipart form" | 0.47 | not a dependency yet | N3 |

Version mismatches: <none | list and how they are handled>

Proposed `docs/refs/manifest.json` additions: <none | entries>

## Contracts
<Interfaces shared between nodes: endpoints and DTO names, schemas, signatures, file formats. Every brief carries this section; it is binding during run.>

## Scenarios
<Every requirement needs a happy-path scenario. Add failure, boundary, authorization, and persistence checks where the feature has those risks; for a category that does not apply, give the reason in the last column.>

| Requirement | Happy path | Other checks | Not applicable (reason) |
| --- | --- | --- | --- |
| A1 | AT-01 | AT-03 | <category: reason, or —> |
| A2 | AT-02 | — | <category: reason, or —> |

### AT-01 — <happy-path outcome>
- Requirement: A1
- Preconditions / data: <accounts, files, or stored state, and the exact sample input>
- Actions: <ordered commands, requests, or click path, with exact input>
- Expected outcome: <visible result, status and body, durable data changes; name what must not change>
- Verification: <how the executor observes it: command, curl, browser steps, or a named test>
- Owners: implementer implementer; executor tester
- Evidence required: <command output, response, screenshot, or data readback>

### AT-02 — <happy-path outcome>
- Requirement: A2
- Preconditions / data: <state and exact input>
- Actions: <exact procedure>
- Expected outcome: <observable result>
- Verification: <command or browser steps>
- Owners: implementer implementer; executor tester
- Evidence required: <observable proof>

### AT-03 — <failure or boundary outcome>
- Requirement: A1
- Preconditions / data: <invalid, empty, duplicate, or boundary input>
- Actions: <exact procedure>
- Expected outcome: <the specific rejection and the state that stays unchanged>
- Verification: <command or browser steps>
- Owners: implementer implementer; executor tester
- Evidence required: <observable proof>

### Execution record
Candidate: —

| Scenario | Status | Observed result and evidence | Blocker |
| --- | --- | --- | --- |
| AT-01 | NOT_RUN | — | — |
| AT-02 | NOT_RUN | — | — |
| AT-03 | NOT_RUN | — | — |

## Team
| Role | Kind | Host agent | Notes |
| --- | --- | --- | --- |
| `main` | orchestrator | this session | owns plan/ and shared files, delegates, records results |
| `implementer` | writer | default subagent | writes a node's code and its tests |
| `tester` | executor | default subagent | runs scenarios on the frozen candidate, edits nothing |
| `reviewer` | reviewer | default subagent | read-only plan review and final review |

## Workflow
- max-parallel: 4
- max-attempts: 2

## Tasks
<!-- consumes, produces and done-when are workflow-tier fields; see the note at the top. -->
### Wave 1: <name>
- [ ] N1 <bounded change and its tests>
  - owner: implementer
  - after: —
  - writes: `src/csv/**`, `tests/csv/**`
  - scenarios: AT-02
  - refs: Python csv module
  - check: `pytest tests/csv`
  - consumes: —
  - produces: `src/csv/parser.py`
  - done-when: parse() returns one record per data row and raises HeaderError for a file without a header row
- [ ] N2 <bounded change and its tests>
  - owner: implementer
  - after: —
  - writes: `src/orders/repo.py`, `tests/orders/test_repo.py`
  - scenarios: AT-01, AT-03
  - check: `pytest tests/orders/test_repo.py`
  - consumes: —
  - produces: `src/orders/repo.py`
  - done-when: bulk_insert() saves every record in one transaction and saves nothing when one record fails

### Wave 2: <name>
- [ ] N3 <bounded change and its tests>
  - owner: implementer
  - after: N1, N2
  - writes: `src/api/import.py`, `tests/api/test_import.py`
  - scenarios: AT-01, AT-02, AT-03
  - refs: Starlette file uploads
  - check: `pytest tests/api`
  - consumes: `src/csv/parser.py`, `src/orders/repo.py`
  - produces: `src/api/import.py`
  - done-when: POST /api/orders/import returns 201 for a valid file and 400 for a file without a header row

### Wave 3: acceptance
- [ ] G1 Run every mandatory scenario on the frozen candidate
  - owner: tester
  - after: N3
  - writes: —
  - scenarios: all
  - gate: test

### Wave 4: review
- [ ] G2 Independent review of the request, the actual diff, and the scenario evidence
  - owner: reviewer
  - after: G1
  - writes: —
  - scenarios: —
  - gate: review

## Verification
- Build / lint / typecheck: `<commands>`
- Tests: `<commands>`
- Smoke: <end-to-end scenario that exercises the changed path for real>
- Wave close: <who runs each node's check when a wave has two or more writers>

Results (filled during run):
- <command> → <observed result>

## Risks and open questions
- <risk or question> — recommended: <answer>

## Plan review
<Replace this line with the first review round. Round, finding, and waiver line formats: `references/plan-review.md`.>

## Changes
<Filled during run: new or changed nodes and fix waves, each with a reason. Contract, scope, or expected-outcome changes need user confirmation; scenario IDs stay stable.>
