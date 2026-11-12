---
title: Command line parser
slug: legacy-running
status: running
created: 2026-11-12
---

# Command line parser

## Goal
The tool reads its options from the command line.

## Acceptance criteria
- [ ] A1 `tool --count 3` prints three lines

## Tasks
### Phase 1: parser
- [x] T1 Add the option parser — files: `src/parse.py` — check: `pytest tests/test_parse.py`
- [ ] T2 Wire the parser into the CLI — files: `src/cli.py` — check: `tool --count 3`
- [!] T3 Publish the package — blocked: no access to the package registry

### Phase 2: docs
- [ ] T4 Document the options — files: `docs/cli.md` — check: read the page

## Verification
- Tests: `pytest`

## Changes
