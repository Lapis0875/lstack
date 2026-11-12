---
title: Greeting command
slug: base-no-review
status: planning
created: 2026-11-12
tier: base
review: pending
---

# Greeting command

## Request
> "Add a `greet` command that says hello." — D1: an empty name is rejected.

## Goal
A user can run `greet NAME` and see a greeting.

## Acceptance criteria
- [ ] A1 `greet NAME` prints `Hello, NAME!` and exits 0
- [ ] A2 `greet` with an empty name prints an error and exits 2

## Won't
- Localized greetings.

## Scenarios
| Requirement | Happy path | Other checks | Not applicable (reason) |
| --- | --- | --- | --- |
| A1 | AT-01 | AT-03 | authorization: local command, no accounts |
| A2 | AT-02 | — | persistence: nothing is stored |

### AT-01 — greeting printed
- Requirement: A1
- Preconditions / data: a fresh checkout; no configuration
- Actions: `./greet Ada`
- Expected outcome: stdout is exactly `Hello, Ada!`; exit code 0
- Verification: run the command in a shell
- Owners: implementer main; executor tester
- Evidence required: command, stdout, exit code

### AT-02 — empty name rejected
- Requirement: A2
- Preconditions / data: a fresh checkout
- Actions: `./greet ""`
- Expected outcome: stderr names the empty argument; stdout is empty; exit code 2
- Verification: run the command in a shell
- Owners: implementer main; executor tester
- Evidence required: command, stderr, exit code

### AT-03 — name with spaces kept
- Requirement: A1
- Preconditions / data: a fresh checkout
- Actions: `./greet "Ada Lovelace"`
- Expected outcome: stdout is exactly `Hello, Ada Lovelace!`; exit code 0
- Verification: run the command in a shell
- Owners: implementer main; executor tester
- Evidence required: command, stdout, exit code

### Execution record
Candidate: —

| Scenario | Status | Observed result and evidence | Blocker |
| --- | --- | --- | --- |
| AT-01 | NOT_RUN | — | — |
| AT-02 | NOT_RUN | — | — |
| AT-03 | NOT_RUN | — | — |

## Tasks
### Phase 1: command
- [ ] T1 Add the greet command — files: `src/greet.py`, `tests/test_greet.py` — check: `pytest tests/test_greet.py`
- [ ] T2 Document the greet command
  - files: `README.md`
  - check: AT-01 by hand

## Verification
- Tests: `pytest`
- Smoke: AT-01 in a shell

## Risks and open questions
- None known — recommended: proceed.

## Plan review

## Changes
(none)
