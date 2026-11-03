---
title: <one-line title>
slug: <kebab-case-slug>
status: planning
created: <YYYY-MM-DD>
---

# <Title>

## Goal
<One sentence: what works after this plan that does not work now, and for whom.>

## Acceptance criteria
- [ ] A1 <observable result: command → expected output, request → response, click path → visible state>
- [ ] A2 …

## Won't
- <explicitly out of scope>

## References
Docs this plan relies on. Prefer `docs/refs/` files; otherwise a pinned Context7 ID and the query used.

| Topic | Source (`docs/refs/…` or Context7 ID + query) | Docs version | Project version | Used by |
| --- | --- | --- | --- | --- |
| <e.g. MSW handlers> | `docs/refs/msw/handlers.md` | 2.15.0 | 2.15.0 | T2 |
| <e.g. Spring Batch CSV import> | `/spring-projects/spring-batch/v6.0.3` "FlatFileItemReader …" | v6.0.3 | not a dependency yet | T4 |

Version mismatches: <none | list and how they are handled>

Proposed `docs/refs/manifest.json` additions: <none | entries>

## Contracts
<Interfaces shared between tasks or agents: endpoints and DTO names, schemas, signatures, file formats. Binding during run.>

## Tasks
### Phase 1: <walking skeleton>
- [ ] T1 <change> — files: `…` — refs: <topic> — check: `<command or scenario>`
- [ ] T2 …

### Phase 2: <name>
- [ ] T3 …

## Verification
- Build / lint / typecheck: `<commands>`
- Tests: `<commands>`
- Smoke: <end-to-end scenario that exercises the changed path for real>

Results (filled during run):
- <command> → <observed result>

## Risks and open questions
- <risk or question> — recommended: <answer>

## Changes
<Filled during run: new or changed tasks, each with a reason. Contract or scope changes need user confirmation.>
