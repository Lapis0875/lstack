# Product acceptance test plan

Authored before implementation by the Orchestrator acting as architect. This is
part of the implementation plan, not a report reconstructed from finished code.
Executable test code is optional at this stage; executable procedures and exact
pass/fail expectations are required. Replace all example placeholders before dispatch.

## Coverage map

Give each Must requirement in SCOPE.md a stable ID (M1, M2, ...). Every Must
maps to at least one happy-path scenario; add boundary, failure, authorization,
and persistence checks wherever the feature has those risks. Record a reason
for an inapplicable risk instead of inventing unrelated requirements.

| Requirement | Happy path | Relevant failure / boundary / security / persistence checks |
| --- | --- | --- |
| M1 <user-visible capability> | AT-01 | AT-02, AT-03 |

## Mandatory scenarios

### AT-01 — <happy-path outcome>
- Requirement: M1
- Preconditions / data: <accounts, ownership, DB state, exact sample input>
- Actions: <ordered requests or browser steps, including route and input>
- Expected outcome: <visible state, status/body, and durable data changes; name what must not change>
- Verification: <browser / curl / named automated test; specify actual product boundary>
- Owners: implementer <BE/FE/both>; executor <Tester, or named verifier if no separate Tester>
- Evidence required: <request/response, observed UI state, saved-data readback, test output as relevant>

### AT-02 — <failure or boundary outcome>
- Requirement: M1
- Preconditions / data: <invalid, duplicate, empty, or boundary input as relevant>
- Actions: <exact procedure>
- Expected outcome: <specific rejection and unchanged state; not merely "handles errors">
- Verification: <command or browser steps>
- Owners: implementer <BE/FE/both>; executor <named verifier>
- Evidence required: <observable proof>

### AT-03 — <authorization or persistence outcome, if relevant>
- Requirement: M1
- Preconditions / data: <two distinct users and an owned row, or a saved record>
- Actions: <cross-user request, reload/readback, or another relevant state transition>
- Expected outcome: <no disclosure/modification, or saved value survives the stated transition>
- Verification: <exact API or browser procedure>
- Owners: implementer <BE/FE/both>; executor <named verifier>
- Evidence required: <observable proof>

## Execution record

The Orchestrator fills this from the Tester's report after implementation, on
the stable candidate; Tester and Reviewer do not edit this document. Initially
every scenario is NOT_RUN. A checked task, passing build, mock-only result, or demo screenshot
alone does not prove every product scenario. Frontend mocks support development;
end-to-end acceptance must exercise the real FE/BE integration.

Candidate: <identifier>

| Scenario | Status (NOT_RUN / PASS / FAIL / BLOCKED) | Observed result and evidence | Blocker, if any |
| --- | --- | --- | --- |
| AT-01 | NOT_RUN | — | — |
| AT-02 | NOT_RUN | — | — |
| AT-03 | NOT_RUN | — | — |

## Release gate

Every mandatory scenario must PASS with evidence. FAIL, BLOCKED, or NOT_RUN is
not completion. Implementers must not weaken expectations to match their code.
Scope or expected-outcome changes require explicit user approval and an entry
here explaining the change; keep scenario IDs stable and notify every owner.
