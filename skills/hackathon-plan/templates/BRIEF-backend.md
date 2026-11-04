# Backend brief

# Target
- Repo: `hackathon-be-spring` (absolute path: …). You own this tree only.
- Do not edit: `plan/`, FE repo.
- Non-goals: anything in SCOPE.md "Won't"; pagination; refresh tokens.

# Change
Implement every endpoint and entity in `plan/CONTRACT.md`, in demo-path order:
1. Walking skeleton first: `<entity>` + `GET/POST /api/<...>` with JPA + one MockMvc test. Report when it runs.
2. Then the rest of the contract.
- Follow the boilerplate's package layout (`auth/`, `user/`, `security/`, `common/`); add one package per entity.
- Before using a library API, read its file under `docs/refs/` (see `docs/refs/INDEX.md` and the contract's References). Missing topic → query Context7 with the pinned ID from `INDEX.md`.
- Ownership: every list/update/delete is scoped to the authenticated user.
- Keep DTO names exactly as in the contract (springdoc schema names feed the FE).
- Contract gap or impossibility → message the Orchestrator; do not improvise fields.

# Acceptance
- Assigned mandatory scenarios: <AT-IDs> in `plan/TEST-PLAN.md`, written before implementation. Implement them and write behavioral tests from their expected outcomes; do not weaken expectations to fit the code.
- Hand off the scenario IDs and real API/data evidence to the named Tester/verifier. All assigned mandatory scenarios require PASS; blocked or unrun is not done.
- `./gradlew test` green; one MockMvc test per endpoint asserting status + JSON field names from the contract.
- `./gradlew bootRun` + `curl` of the demo path pasted in the report.
- `GET /v3/api-docs` lists every contract DTO by name.
