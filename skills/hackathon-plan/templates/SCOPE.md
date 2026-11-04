# SCOPE

## Problem (1 line, given)
<copy the problem statement>

## Must (max 4, 3-hour budget; auth is already done)
1. M1 — User can …
2. M2 — User can …
3. M3 — User can …

Before dispatch, every Must ID must map to concrete mandatory scenarios in
`TEST-PLAN.md`; a demo-path mention alone is not an acceptance specification.

## Demo path (exact click sequence)
1. Open `/login` → log in as `demo@x.com`
2. …
3. …

## Won't (explicitly out)
- …

## Screens ↔ endpoints
| Screen | Route | Endpoints called |
| --- | --- | --- |
| Home | `/` | `GET /api/me`, `GET /api/…` |
| … | `/…` | `POST /api/…` |
