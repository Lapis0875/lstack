---
name: openai-dev-team
description: >-
  Run an OpenAI-only agentic development team: an Orchestrator (GPT-6 Astra)
  that scopes, designs contracts, and integrates; Implementers (GPT-6.1 Terra)
  that write production code and its tests; a Tester (GPT-6 Luna) that
  executes verification; and a Reviewer (GPT-6.1 Sol) that reviews read-only.
  Use when the user asks for the OpenAI dev team, an OpenAI-only multi-agent
  build, or orchestration with Orchestrator/Implementer/Tester/Reviewer roles
  on OpenAI models.
---

# OpenAI dev team

The top-level session is the Orchestrator. It is the only role that
delegates. Named role workers never spawn other agents. Follow higher-priority
user and repository instructions; this skill does not override them.

## Roles and model routes

| Role | Primary model | Fallback (only if the primary is not accessible) | Responsibility |
| --- | --- | --- | --- |
| Orchestrator | GPT-6 Astra (`openai-codex/gpt-6-astra`) | GPT-6.1 Sol, effort `high` | Scope, architecture, contracts, ownership, task briefs, integration, routing findings |
| Implementer | GPT-6.1 Terra (`openai-codex/gpt-6.1-terra`) | GPT-6.1 Sol, effort `medium` | One bounded slice: production code **and the tests for that slice** |
| Reviewer | GPT-6.1 Sol, effort `high` (`openai-codex/gpt-6.1-sol:high`) | none | Independent read-only review of the stable candidate |
| Tester | GPT-6 Luna, effort `medium` (`openai-codex/gpt-6-luna:medium`) | none | Executes builds, tests, and acceptance scenarios on the stable candidate; edits nothing |

Selector syntax shown is omp's `provider/model:effort`. In Codex CLI use the
bare model name (`-m gpt-6-astra`) and set effort with
`-c model_reasoning_effort=<level>`.

Routing rules:
- Use exactly the listed route. Switch to the listed fallback only after the primary fails with an access, availability, or quota error. Record the failure that caused the switch.
- No fallback is listed for Reviewer or Tester. If their route is unavailable, stop that role and report it to the user. Do not substitute another model.
- Never fall back to a non-OpenAI model. Never escalate effort on your own.
- For every role result, record the model and effort observed in host runtime metadata. Prompt text, configuration intent, and a model's self-description do not count as evidence.
- If the Orchestrator session itself is not running on Astra (or on Sol `high` as the fallback), tell the user before delegating anything.

Spawn only the roles the task needs. A one-file change can be done by the
Orchestrator inline. State why delegation was skipped.

## 1. Scope and design (Orchestrator)

There is no separate architect model or worker. The Orchestrator acts as the
**architect** during planning and owns the mandatory product acceptance test
specification before implementation is dispatched:

1. State the requested outcome, non-goals, and stable requirement IDs.
2. Read the relevant code and conventions. Reuse existing patterns.
3. Define the shared contracts between slices: API shapes, schemas, interfaces, file formats. Put them in one file that each brief references.
4. Write mandatory product acceptance scenarios in the implementation plan before coding starts. With `hackathon-plan`, use `plan/TEST-PLAN.md` from its template; otherwise embed the same specification in the plan. Give each scenario a stable ID, linked requirement, preconditions/test data, exact actions, expected observable outcome (including data changes or unchanged state), verification method, implementer/executor owners, and required evidence. Test source code is not required yet. Cover every Must requirement's happy path and relevant boundaries, failures, authorization, and persistence; explain inapplicable risk categories. Generic items such as "tests pass" or "login works" are insufficient.
5. Split the work into slices with **one writer per path**. Shared interfaces, migrations, generated files, and lockfiles each get exactly one owner. Typical full-stack split: one Backend Implementer and one Frontend Implementer. Assign scenario IDs to briefs; do not dispatch implementation until the acceptance specification covers every Must requirement.

For a new project, finish the read-only design before scaffolding or production
file writes. Plan artifacts may record that design. Expectations come from the
user's requirements, not the finished implementation; changing scope or expected
outcomes requires explicit user approval.

## 2. Implementation (Implementers)

Every Implementer brief contains:
- `# Target`: repository and allowed paths, forbidden paths, non-goals.
- `# Contract`: the shared contract file. The Implementer follows it exactly and messages the Orchestrator instead of deviating.
- `# Change`: what to build, in priority order.
- `# Tests`: the prewritten scenario IDs this slice must satisfy. Write production code and its tests from those expectations, covering behavior, boundaries, and error cases. Planning may be prose-only; the Implementer still owns test-code delivery.
- `# Acceptance`: link the mandatory product acceptance specification and name the observable checks and commands for the assigned scenario IDs.
- `# Report`: every changed or created file, the commands run with their real output, and any deviation.

Implementers may run focused builds and tests for their own slice when no
other writer is active in the same tree. The full acceptance run belongs to
the Tester. Implementers never weaken, skip, or delete a test to make it pass.

## 3. Integration (Orchestrator)

Collect every Implementer result, including untracked files. Resolve contract
mismatches, then declare one **stable candidate**: a named identifier plus its
actual changed-file set. Testing and review never overlap with writing. If any
file changes, the candidate is new.

## 4. Testing (Tester)

The Orchestrator gives the Tester the candidate identifier, the acceptance
specification written before implementation, assigned scenario IDs, the exact
commands (build, unit/integration tests, lint, typecheck), and real product
scenarios (for example, run the server and walk the flow in a browser or curl).

The Tester executes every mandatory scenario unchanged and records its ID,
`PASS` / `FAIL` / `BLOCKED` / `NOT_RUN`, the observed result, and evidence.
The Tester does not edit source, expectations, tests, fixtures, or snapshots.
Build success or mock-only checks do not replace real integration acceptance.
Blocked, unexecuted, or inconclusive requirements are not PASS.

## 5. Review (Reviewer)

The Orchestrator gives the Reviewer the original request, prewritten acceptance
specification, contract, candidate's actual diff (new files included), and the
Tester's per-scenario evidence. The Reviewer checks requirement coverage and
that expectations were not weakened after implementation. A summary alone is
not enough. Review is read-only; report concrete defects with severity,
file:line, observed behavior, and expected behavior.

## 6. Fix loop

Send every finding to the Implementer that owns the path; this includes test
defects, since Implementers own their tests. After the fix, name the new
candidate, have the Tester rerun the affected requirements, and get a fresh
Reviewer pass. Report completion only when every acceptance criterion has
Tester PASS evidence and the Reviewer has no open defect.

## Boundaries

- Never commit, push, deploy, touch production services, or change global settings without explicit user authorization.
- Preserve existing user changes. Treat unexpected repository changes as the user's.
- Spawning happens only through the host's native subagent mechanism. Never launch an agent CLI from a shell, eval, or MCP to get around spawn rules.
