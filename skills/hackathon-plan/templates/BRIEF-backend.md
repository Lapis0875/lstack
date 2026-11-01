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
- Ownership: every list/update/delete is scoped to the authenticated user.
- Keep DTO names exactly as in the contract (springdoc schema names feed the FE).
- Contract gap or impossibility → message the Orchestrator; do not improvise fields.

# Acceptance
- `./gradlew test` green; one MockMvc test per endpoint asserting status + JSON field names from the contract.
- `./gradlew bootRun` + `curl` of the demo path pasted in the report.
- `GET /v3/api-docs` lists every contract DTO by name.
