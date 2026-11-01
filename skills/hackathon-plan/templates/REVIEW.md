# Reviewer checklist (run per slice, not once at the end)

Candidate: <BE commit/tree state> + <FE commit/tree state>

## Contract conformance
- [ ] Every endpoint in CONTRACT.md exists in `/v3/api-docs` with the exact path and DTO names.
- [ ] FE `src/api/schema.d.ts` regenerated from the current BE (no hand edits).
- [ ] Error bodies are ProblemDetail; FE shows `detail`.
- [ ] Ownership: user A cannot read/modify user B's rows (try it with two tokens).

## Demo path
- [ ] Walk SCOPE.md "Demo path" in a browser against the real BE. Note the first step that fails.
- [ ] Fresh DB (restart BE) → demo path still works from signup.

## Scope
- [ ] Nothing from "Won't" was built.
- [ ] Every Must feature has at least one screen and one endpoint.

## Report
Per finding: severity (blocks demo / visible / cosmetic), repo, file:line, what was observed, what the contract says.
