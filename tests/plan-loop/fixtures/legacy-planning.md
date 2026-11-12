---
title: Rename settings keys
slug: legacy-planning
status: planning
created: 2026-11-12
---

# Rename settings keys

## Goal
Settings files use snake_case keys.

## Acceptance criteria
- [ ] A1 `python3 -m app.settings --dump` prints only snake_case keys

## Won't
- Migrating existing user settings files.

## Contracts
Key names map one to one: `maxItems` becomes `max_items`.

## Tasks
### Phase 1: rename
- [ ] T1 Rename the keys — files: `src/settings.py` — check: `pytest tests/test_settings.py`
- [ ] T2 Update the settings page — files: `docs/settings.md` — check: read the page

## Verification
- Tests: `pytest`
- Smoke: `python3 -m app.settings --dump`

## Risks and open questions
- None known — recommended: proceed.

## Changes
