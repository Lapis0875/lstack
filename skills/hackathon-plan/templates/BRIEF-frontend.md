# Frontend brief

# Target
- Repo: `hackathon-fe-vite` (absolute path: …). You own this tree only.
- Do not edit: `plan/`, BE repo.
- Non-goals: anything in SCOPE.md "Won't"; theming beyond shadcn defaults; SSR.

# Change
Implement every screen in `plan/SCOPE.md` "Screens ↔ endpoints" using `plan/CONTRACT.md`:
1. Add MSW handlers for all new endpoints from the contract first (in-memory). Run on `pnpm dev:mock` until BE is up.
2. Walking skeleton: the first demo-path screen against the real API (`pnpm gen:api` once BE serves `/v3/api-docs`). Report when it runs.
3. Then the remaining screens, demo-path order.
- Use the existing patterns: `src/api/client.ts` (openapi-fetch), TanStack Query hooks per resource, react-hook-form + zod for forms, shadcn components.
- Before using a library API, read its file under `docs/refs/` (see `docs/refs/INDEX.md` and the contract's References). Dependencies are pinned to the documented versions; do not bump them during the event.
- Show server ProblemDetail `detail` / `errors` on failures.
- Contract gap → message the Orchestrator; do not invent fields.

# Acceptance
- Assigned mandatory scenarios: <AT-IDs> in `plan/TEST-PLAN.md`, written before implementation. Implement them and write behavioral tests from their expected outcomes; do not weaken expectations to fit the UI.
- MSW is a development aid, not final integration evidence. The named Tester/verifier executes the required real-backend scenarios and records their IDs and outcomes; blocked or unrun is not done.
- `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build` green.
- Demo path walked in a real browser against the real BE; URLs + visible text log + one screenshot in the report.
