# Reviewer checklist (run per slice, not once at the end)

Candidate: <BE commit/tree state> + <FE commit/tree state>

## Prewritten product acceptance
- [ ] `TEST-PLAN.md` was specified before implementation and every Must ID in SCOPE.md maps to a mandatory scenario.
- [ ] Scenarios contain preconditions/data, actions, expected observable outcomes and data effects, verification methods, owners, and required evidence.
- [ ] Happy paths and relevant failures, boundaries, authorization, and persistence are covered; inapplicable risk categories have reasons.
- [ ] The named Tester/verifier executed every mandatory scenario on the stable candidate, using real integration where required, with per-ID PASS evidence.
- [ ] No expectations were weakened to match the implementation. FAIL, BLOCKED, or NOT_RUN prevents completion; changes to scope/outcomes require explicit user approval.

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
