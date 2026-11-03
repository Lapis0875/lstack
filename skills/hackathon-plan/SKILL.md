---
name: hackathon-plan
description: >-
  Turn an already-defined problem into a dispatch-ready full-stack build plan
  in 30 minutes, then run a 3-hour Orchestrator / Backend Implementer /
  Frontend Implementer / Reviewer build on top of the hackathon boilerplates.
  Use when the user has a time-boxed hackathon or contest, says "30분 안에
  계획", "3시간 안에 구현", "빠르게 구현 계획", or asks to start orchestration
  from a fixed problem statement. Not for idea validation or open-ended design.
---

# Hackathon plan (30-minute plan, 3-hour build)

Goal: finish planning in 30 minutes by writing a **contract**, not a design
document, and hand the rest to implementers. The Orchestrator decides only what
Frontend and Backend must agree on. Everything inside one side is the
implementer's call. The specification is in English; run the session in the
user's language.

## Preconditions

- Problem statement already fixed. If not, stop and use `idea-validation` first.
- Boilerplates cloned (both ship with signup/login/`/api/me` working end to end):
  - BE: `hackathon-be-spring` (Spring Boot 3, Security + JWT, springdoc, H2 default / Postgres profile)
  - FE: `hackathon-fe-vite` (Vite + React + TS, Tailwind + shadcn/ui, react-router, TanStack Query, openapi-fetch, MSW)
  - Local path on the author's machine: `~/Projects/Boilerplates/`.
- Stack is not negotiable during the event. Do not open a stack discussion.

## Roles

| Role | Owns | Does not |
| --- | --- | --- |
| Orchestrator (you) | scope cut, API contract, screen↔endpoint map, worker briefs, contract changes, final demo path | write feature code, pick libraries inside FE or BE |
| Backend Implementer | `hackathon-be-spring` tree | touch FE tree, change contract silently |
| Frontend Implementer | `hackathon-fe-vite` tree | touch BE tree, change contract silently |
| Reviewer | reads both trees + contract, runs the demo path | edit code |

One writer per tree. Contract changes go through the Orchestrator and are
broadcast to both implementers and the Reviewer.

## 30-minute timebox

Use a visible timer. If a step overruns, cut scope, not the next step.

### 0–5 min: scope cut
Write `plan/SCOPE.md` from `templates/SCOPE.md`:
- Must: 3–4 user-visible features maximum for 3 hours. Each is one sentence
  "user can …". Auth is already done; do not list it.
- Demo path: the exact click sequence shown at the end. Everything not on it is Should/Won't.
- Won't: write it down so nobody builds it.

### 5–15 min: API contract
Write `plan/CONTRACT.md` from `templates/CONTRACT.md`. This is the only shared
interface. Per endpoint: method, path, request body, success response, error
statuses. Errors are RFC 9457 ProblemDetail (already wired in the boilerplate).
Entities: field list only, no indexes or relations beyond foreign keys.

Rules that keep this to 10 minutes:
- Reuse the boilerplate's conventions: `/api/...`, Bearer JWT, ProblemDetail, DTO record names ending in `Request`/`Response`.
- One list endpoint + one create endpoint per Must feature is usually enough. Add update/delete only if on the demo path.
- No pagination, no filtering, no file upload unless on the demo path.
- Name the DTO classes; the BE's springdoc output and the FE's generated types must match these names.
- Fill the contract's `## References` table from each boilerplate's `docs/refs/INDEX.md`: one row per library a Must feature touches (for example Spring Batch for a CSV import, AWS S3 for uploads). Copy the file path and pinned Context7 ID; do not research during the timebox.

### 15–20 min: screen ↔ endpoint map
Fill the table in `plan/SCOPE.md`: one row per screen (3–5 screens), listing
the endpoints it calls. A screen with no endpoint or an endpoint with no screen
is a scope bug; fix it now.

### 20–27 min: worker briefs
Fill `templates/BRIEF-backend.md` and `templates/BRIEF-frontend.md` into
`plan/`. Each brief has `# Target` (repo path, allowed paths, non-goals),
`# Change` (feature list referencing the contract by endpoint), `# Acceptance`
(observable checks, commands to run). Reviewer brief = `templates/REVIEW.md`,
which is mostly the contract turned into a checklist.

Do not write implementation steps, folder layouts, or component trees in the
briefs. Implementers decide those. Briefs do point implementers at
`docs/refs/` and the contract's References table.

For non-contest work, `plan-loop` runs the same contract-first planning with a
single plan file and a run loop that drives it to completion.

### 27–30 min: dispatch
Dispatch BE and FE in the same batch. First assignment for both is the
**walking skeleton**: one Must feature end to end (BE endpoint with DB, FE
screen calling it for real). Reviewer starts when the skeleton lands.

## 3-hour schedule

| Window | Orchestrator | BE | FE | Reviewer |
| --- | --- | --- | --- | --- |
| 0:00–0:30 | contract + briefs | boot boilerplate, read contract | boot boilerplate, start MSW mocks from contract | idle |
| 0:30–1:15 | answer blockers only | skeleton: 1 endpoint + entity + test | skeleton: 1 screen on real API | smoke the skeleton; contract diff |
| 1:15–2:30 | approve contract changes | remaining Must | remaining Must | per-slice contract check |
| 2:30–3:00 | lock demo path | bugs only | bugs only | run demo path twice |

Hard rules:
1. FE never waits for BE: MSW handlers come straight from the contract. Swap to the real API when the endpoint exists.
2. Contract change = Orchestrator approval + broadcast. No silent field renames.
3. Reviewer checks per slice, not once at the end. Checklist = contract.
4. At 2:30, stop adding features regardless of state. A working 3-feature demo beats a broken 5-feature one.

## Artifacts

```
plan/
  SCOPE.md          # Must / demo path / Won't / screen↔endpoint map
  CONTRACT.md       # endpoints, DTOs, entities, errors
  BRIEF-backend.md
  BRIEF-frontend.md
  REVIEW.md
```

Keep `plan/` in whichever repo hosts the monorepo or in the BE repo; it is
read-only for implementers.

## Anti-patterns that cost the hour

- Deciding folder structure, component split, or service layering for the implementers.
- Writing sequence diagrams for CRUD.
- Comparing libraries during the event.
- A "complete" data model with every field you might need. Add fields when a Must feature needs them.
- Reviewer waiting for "the final candidate".
