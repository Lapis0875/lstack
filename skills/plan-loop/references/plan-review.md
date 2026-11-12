# Plan review

An independent check of the plan before the user sees it for approval. The
order is fixed: machine check, review rounds, the user's approval, then
`advance approved`.

## 1. Before the first round

Run `check --phase draft` and fix the plan until it reports no error. Do not
spend a review round on a plan with check errors. Without python3, walk the
manual checklist in `references/plan-format.md` instead.

## 2. Who reviews

- Someone who did not write the plan, in a fresh context.
- Team and workflow plans: the role whose Kind is `reviewer` in `## Team`,
  through its Host agent.
- Base plans: a read-only subagent.
- A host without subagents: self review (section 9).

The reviewer is read-only. It edits nothing, may read the repository, and may
run read-only commands to test a premise. The plan author records the result.

## 3. Inputs

The reviewer gets the plan file path, read access to the repository, the round
number, and the digest of the plan as handed over. Nothing else: no
conversation summary. Whether the plan can be understood on its own is part of
the review.

The reviewer compares the plan with its own `## Request`,
`## Acceptance criteria`, `## Scenarios` and `## Contracts`, and with the
repository's instructions and code. From round 2 on, the earlier findings and
what changed for each of them are in `## Plan review`.

## 4. Blocking codes

Only these six block. Everything else is a non-blocking note.

| Code | Name | Blocks when |
| --- | --- | --- |
| B1 | Broken trace | A Request item or decision has no requirement; a requirement has no happy-path scenario; a scenario has no implementing task or no executor. |
| B2 | Undecidable | A procedure or expected outcome is vague enough that two executors could reach different PASS or FAIL verdicts. |
| B3 | Contradiction | The plan conflicts with the Request, a confirmed decision, repository instructions, or its own Contracts or Won't. |
| B4 | False premise | A cited file, symbol, command, API or version does not exist or behaves differently. The reviewer gives `path:line` or documentation as evidence. |
| B5 | Not executable | A dependency cycle; a node that starts without its inputs; overlapping write scopes of nodes that run at the same time; a gate scheduled before its writers; a task whose decision is still open. |
| B6 | Out of bounds | An unrequested commit, push, deploy, global settings change or data deletion; a compatibility break with no migration path. |

A blocking finding states its ID (`F1`, `F2`, … numbered across all rounds),
its code, the location, the evidence, and the smallest change that resolves it.

## 5. Rounds

- **Round 1** reviews the whole plan. Verdict: `PASS` (no blocking finding) or
  `REVISE`.
- **Fixing.** Make the smallest edit that resolves each blocking finding. Do not
  widen the scope. A finding you disagree with gets `status: rejected` with the
  reason, and goes to the user at approval.
- **Round 2 and later** use a new reviewer context. The scope is the open
  findings and the parts changed since the previous round. A new blocking
  finding is accepted only for a changed part, or under B4 or B6.
- **Stop** when a round returns PASS, when three rounds are done, or when a round
  ends with the same set of open findings as the round before. In the last two
  cases, stop and ask the user to choose: more fixes, a waiver, or abandoning
  the plan.
- **Budget.** Review time is separate from the 30-minute drafting timebox, and
  capped at three rounds.

## 6. Digest

`digest --short` prints the review digest: the first 12 hex digits of the
SHA-256 of the plan after these steps.

1. Drop a UTF-8 BOM and read `\r\n` and lone `\r` as `\n`.
2. Delete the `status:` and `review:` lines inside the front matter.
3. Delete the `## Plan review` section, from its heading to the next H2.
4. Strip trailing spaces and tabs from every line, drop blank lines at the end,
   join with `\n`, and end with one `\n`.
5. Hash the UTF-8 bytes.

Status changes and review records therefore do not change the digest; any
other edit does.

Take the digest when you hand the plan to the reviewer and record that value in
the round line. Do not edit the plan while a round runs. If it changed anyway,
the round covered the old digest and `check --phase approve` reports
`E-REVIEW-STALE`: run another round.

Without python3 the digest is `unavailable`. `check` cannot tell whether the
plan changed after such a round (`W-REVIEW-NODIGEST`), so any edit after the
round reopens review.

## 7. Recording

The plan author writes each round into `## Plan review`, newest last:

    - Round 1 — reviewer: reviewer (provider/model, effort high) — mode: independent — digest: 1c87d6278f5f — verdict: REVISE
      - F1 [B4] AT-03 runs `make smoke`, which the Makefile does not define — status: fixed (AT-03 now runs `make e2e`)
      - F2 [B3] N4 writes `README.md`, which Won't excludes — status: rejected (the user asked for the README line in D3)
    - Round 2 — reviewer: reviewer (provider/model, effort high) — mode: independent — digest: fa89403e20be — verdict: PASS

- Round line: `- Round <n> — reviewer: <name> — mode: independent|self — digest: <12 hex>|unavailable — verdict: PASS|REVISE`.
  Put the provider, model and effort that the host's runtime metadata shows
  for the reviewer after its name.
- Finding line, indented under its round:
  `  - F<n> [B<k>] <text> — status: open|fixed|rejected|waived <note>`.
  The note says what changed (`fixed`), why (`rejected`), or when the user
  decided (`waived`). `open` blocks approval; `rejected` does not, but the user
  sees it in the approval summary.
- Waiver line, written only on the user's explicit decision:
  `- Waived by user: <YYYY-MM-DD> — <reason>`. It skips every review gate.
- Other lines in the section (non-blocking notes, how the check was run) are
  allowed and ignored by the parser. Do not start them with `- Round` or
  `- Waived by user`.

## 8. Approval

1. Show the user the plan path and the approval summary, which includes the
   review result: the final verdict, the number of rounds, every `rejected` or
   still-`open` finding, and "self review" when the last round was
   `mode: self`.
2. If the user asks for changes, make them, then run one more round scoped to
   the changes, or record the user's waiver.
3. Run `advance approved`. It passes only when `check --phase approve` reports
   no error: the last round is `PASS`, its digest equals the current digest,
   and no finding is `open`; or a waiver line exists. It then writes
   `status: approved` and `review: passed` (or `review: waived` with a waiver).
   Otherwise it exits 1 and changes nothing.

| Code | Meaning |
| --- | --- |
| `E-REVIEW-MISSING` | no round and no waiver |
| `E-REVIEW-VERDICT` | the last round is REVISE |
| `E-REVIEW-STALE` | the plan changed after the last round |
| `E-REVIEW-OPEN` | a finding is still open |
| `W-REVIEW-NODIGEST` | the last round has digest `unavailable` (warning) |
| `W-REVIEW-SELF` | the last round is a self review (warning) |

Without python3, check the same conditions by hand and set both front matter
lines yourself.

## 9. Self review

Use it only when the host cannot start a subagent.

- One round, `mode: self`, reviewer `self` (plus the session's provider and
  model when known).
- Start a fresh pass: read the plan file from the top, not the conversation,
  and answer every question in the checklist below.
- Fix each blocking item at once with the smallest edit, and record it as a
  finding with `status: fixed`. When every item holds, take the digest of the
  fixed plan and record the round as `PASS`. If an item needs a decision only
  the user can make, record the round as `REVISE` with that finding `open` and
  ask the user.
- Say "self review" in the approval summary. `check --phase approve` warns with
  `W-REVIEW-SELF`.

Checklist:

- [ ] B1 Every Request item and decision maps to a requirement or a Won't line.
- [ ] B1 Every requirement has a happy-path scenario in the coverage table.
- [ ] B1 Every scenario has an implementing task (team: a work node listing it) and an executor.
- [ ] B2 Every scenario names exact inputs, exact expected output, and what must stay unchanged; two executors would reach the same verdict.
- [ ] B3 Nothing contradicts the Request, a confirmed decision, repository instructions, Contracts or Won't.
- [ ] B4 Every cited file, symbol, command, API and version exists and behaves as stated; open the file or run a read-only command to confirm it.
- [ ] B5 No cycle; every node has its inputs when it starts; nodes that run together do not share write paths; gates come after their writers; no task waits on an open decision.
- [ ] B6 No unrequested commit, push, deploy, global settings change or data deletion; every compatibility break has a migration path.

## 10. Reviewer brief

Hand this to the reviewer with the angle-bracket values filled in.

```text
Review the implementation plan at <plan path> before the user approves it.
Round <n>. Review digest of the plan as handed over: <12 hex>.

You are read-only. Do not edit the plan or any other file. Read the repository
as needed and run only read-only commands. You get no conversation summary on
purpose: judge the plan by what the file says.

Compare the plan with its own Request, Acceptance criteria, Scenarios and
Contracts sections, and with the repository's instructions and code.

Block only for these reasons:
B1 Broken trace: a Request item or decision has no requirement; a requirement
   has no happy-path scenario; a scenario has no implementing task or executor.
B2 Undecidable: a procedure or expected outcome is vague enough that two
   executors could disagree on PASS or FAIL.
B3 Contradiction: conflict with the Request, a confirmed decision, repository
   instructions, or the plan's own Contracts or Won't.
B4 False premise: a cited file, symbol, command, API or version does not exist
   or behaves differently. Give path:line or documentation as evidence.
B5 Not executable: a cycle, a node starting without its inputs, overlapping
   write scopes of concurrent nodes, a gate before its writers, a task whose
   decision is still open.
B6 Out of bounds: an unrequested commit, push, deploy, global settings change
   or data deletion; a compatibility break with no migration path.
Everything else is a non-blocking note.

From round 2: check whether each finding still open in the Plan review section
is resolved, and review the parts changed since round <n-1>. Raise a new
blocking finding only for a changed part, or under B4 or B6.

Report:
1. Verdict: PASS (no blocking finding) or REVISE.
2. Blocking findings, numbered from F<next>: code, location, evidence, and
   the smallest change that resolves it.
3. For each earlier open finding: resolved or not, and why.
4. Non-blocking notes, separately.
```
