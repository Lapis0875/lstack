---
title: CSV import
slug: team-gate-owner
status: planning
created: 2026-11-12
tier: team
team: generic
review: pending
---

# CSV import

## Request
> "CSV 파일을 올리면 주문이 등록되게 해 줘." — D1: 헤더 없는 파일은 거부한다.

## Goal
A user can import orders from a CSV file.

## Acceptance criteria
- [ ] A1 Uploading a valid CSV creates one order per row
- [ ] A2 A CSV without a header row is rejected and nothing is saved

## Scenarios
| Requirement | Happy path | Other checks | Not applicable (reason) |
| --- | --- | --- | --- |
| A1 | AT-01 | — | authorization: endpoint is internal-only |
| A2 | AT-02 | — | — |

### AT-01 — valid file creates orders
- Requirement: A1
- Preconditions / data: empty `orders` table; `fixtures/3rows.csv`
- Actions: `curl -F file=@fixtures/3rows.csv localhost:8080/api/orders/import`
- Expected outcome: 201; `orders` has exactly 3 rows; no other table changes
- Verification: curl + `SELECT count(*) FROM orders`
- Owners: implementer implementer; executor tester
- Evidence required: response body, row count

### AT-02 — headerless file rejected
- Requirement: A2
- Preconditions / data: empty `orders` table; `fixtures/noheader.csv`
- Actions: same request with `noheader.csv`
- Expected outcome: 400 with `detail` naming the header; `orders` still empty
- Verification: curl + row count
- Owners: implementer implementer; executor tester
- Evidence required: response body, row count

### Execution record
Candidate: —
| Scenario | Status | Observed result and evidence | Blocker |
| --- | --- | --- | --- |
| AT-01 | NOT_RUN | — | — |
| AT-02 | NOT_RUN | — | — |

## Team
| Role | Kind | Host agent | Notes |
| --- | --- | --- | --- |
| `main` | orchestrator | — | owns plan/ and shared files |
| `implementer` | writer | — | code and its tests |
| `tester` | executor | — | runs scenarios, edits nothing |
| `reviewer` | reviewer | — | read-only |

## Tasks
### Wave 1: parser and endpoint
- [ ] N1 CSV parser with header validation
  - owner: implementer
  - after: —
  - writes: `src/csv/**`, `tests/csv/**`
  - scenarios: AT-02
  - check: `pytest tests/csv`
- [ ] N2 Order repository bulk insert
  - owner: implementer
  - after: —
  - writes: `src/orders/repo.py`, `tests/orders/test_repo.py`
  - scenarios: AT-01
  - check: `pytest tests/orders/test_repo.py`

### Wave 2: wiring
- [ ] N3 Import endpoint
  - owner: implementer
  - after: N1, N2
  - writes: `src/api/import.py`, `tests/api/test_import.py`
  - scenarios: AT-01, AT-02
  - check: `pytest tests/api`

### Wave 3: acceptance
- [ ] G1 Execute all mandatory scenarios on the frozen candidate
  - owner: reviewer
  - after: N3
  - writes: —
  - scenarios: all
  - gate: test

### Wave 4: review
- [ ] G2 Independent review of diff and evidence
  - owner: reviewer
  - after: G1
  - writes: —
  - scenarios: —
  - gate: review

## Verification
- Tests: `pytest`
- Smoke: AT-01 against a running server

## Plan review
- Round 1 — reviewer: reviewer — mode: independent — digest: 4b79cf77e5d5 — verdict: PASS

## Changes
(none)
