"""Line-level plan edits keep line ends, BOM and untouched lines byte for byte."""

from __future__ import annotations

import unittest

from plan_loop_support import TempRepo, fixture_text, replace_once

from planlib import checks, mutate, planfile

AT = "2026-11-12T10:00:00Z"
T1_HEAD = "- [ ] T1 Add the greet command — files: `src/greet.py`, `tests/test_greet.py` — check: `pytest tests/test_greet.py`"
T1_WRITES = ["src/greet.py", "tests/test_greet.py"]


class EditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_crlf_and_bom_are_kept(self) -> None:
        raw = b"\xef\xbb\xbf" + fixture_text("team-ok").replace("\n", "\r\n").encode("utf-8")
        plan = self.repo.parse("team-ok", "", raw=raw)
        change = mutate.node_command(plan, "done", "N1", mutate.NodeOptions(evidence="pytest ok"), AT)
        out = change.plan_bytes
        self.assertTrue(out.startswith(b"\xef\xbb\xbf---\r\n"))
        self.assertNotIn(b"\n", out.replace(b"\r\n", b""))
        self.assertIn(b"- [x] N1 CSV parser with header validation\r\n", out)
        self.assertIn(b"  - check: `pytest tests/csv`\r\n  - evidence: pytest ok\r\n- [ ] N2 ", out)
        self.assertEqual(len(out), len(raw) + len(b"  - evidence: pytest ok\r\n"))

    def test_untouched_lines_are_identical(self) -> None:
        text = fixture_text("base-ok")
        plan = self.repo.parse("base-ok", text)
        change = mutate.record_scenario(plan, "AT-02", "FAIL", "exit 0", AT, candidate="c7", blocker=None)
        before = text.split("\n")
        after = change.plan_bytes.decode("utf-8").split("\n")
        self.assertEqual(len(before), len(after))
        diff = [(before[i], after[i]) for i in range(len(before)) if before[i] != after[i]]
        self.assertEqual(diff, [("Candidate: —", "Candidate: c7"), ("| AT-02 | NOT_RUN | — | — |", "| AT-02 | FAIL | exit 0 | — |")])

    def test_insert_after_last_line_without_newline(self) -> None:
        plan = self.repo.parse("base-ok", fixture_text("base-ok").rstrip("\n"))
        editor = mutate.Editor(plan)
        editor.insert_after(len(plan.lines) - 1, "tail")
        self.assertTrue(editor.render().decode("utf-8").endswith("(none)\ntail\n"))

    def test_front_matter_review_inserted_when_missing(self) -> None:
        text = fixture_text("base-ok").replace("review: pending\n", "")
        plan = self.repo.parse("base-ok", text)
        editor = mutate.Editor(plan)
        mutate.set_front_matter(editor, plan, "review", "passed")
        rendered = editor.render().decode("utf-8")
        self.assertIn("status: planning\nreview: passed\ncreated:", rendered)

    def test_blocked_field_replaced_not_duplicated(self) -> None:
        text = fixture_text("team-ok").replace("  - check: `pytest tests/csv`\n", "  - check: `pytest tests/csv`\n  - blocked: old reason\n")
        plan = self.repo.parse("team-ok", text)
        change = mutate.node_command(plan, "block", "N1", mutate.NodeOptions(reason="new reason"), AT)
        rendered = change.plan_bytes.decode("utf-8")
        self.assertEqual(rendered.count("  - blocked: "), 1)
        self.assertIn("  - blocked: new reason\n", rendered)
        self.assertIn("- [!] N1 ", rendered)


class InlineBlockedTest(unittest.TestCase):
    """G2 F3: the inline ` — blocked:` field ends where the parser ends it, at the next inline field."""

    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def reset_t1(self, head: str):
        plan = self.repo.parse("base-ok", replace_once(fixture_text("base-ok"), T1_HEAD + "\n", head + "\n"))
        change = mutate.node_command(plan, "reset", "T1", mutate.NodeOptions(), AT)
        line = next(text for text in change.plan_bytes.decode("utf-8").split("\n") if text.startswith("- [ ] T1 "))
        return line, change.plan.node("T1")

    def test_blocked_first_middle_last_and_continued(self) -> None:
        files = "files: `src/greet.py`, `tests/test_greet.py`"
        check = "check: `pytest tests/test_greet.py`"
        cases = {
            "first": f"- [!] T1 Add the greet command — blocked: waiting — {files} — {check}",
            "middle": f"- [!] T1 Add the greet command — {files} — blocked: waiting — {check}",
            "last": f"- [!] T1 Add the greet command — {files} — {check} — blocked: waiting",
            "continued": f"- [!] T1 Add the greet command — blocked: waiting — on the db — {files} — {check}",
        }
        for label, head in cases.items():
            with self.subTest(position=label):
                line, node = self.reset_t1(head)
                self.assertEqual(line, T1_HEAD)
                self.assertEqual((node.title, node.writes, node.issues), ("Add the greet command", T1_WRITES, []))
                self.assertEqual(node.fields["check"], "`pytest tests/test_greet.py`")
                self.assertNotIn("blocked", node.fields)

    def test_team_head_keeps_owner_and_after(self) -> None:
        text = replace_once(
            fixture_text("team-ok"),
            "- [ ] N1 CSV parser with header validation\n  - owner: implementer\n  - after: —\n",
            "- [!] N1 CSV parser with header validation — blocked: waiting — owner: implementer — after: none\n",
        )
        change = mutate.node_command(self.repo.parse("team-ok", text), "reset", "N1", mutate.NodeOptions(), AT)
        self.assertIn("- [ ] N1 CSV parser with header validation — owner: implementer — after: none\n", change.plan_bytes.decode("utf-8"))
        node = change.plan.node("N1")
        self.assertEqual((node.owner, node.after, node.issues), ("implementer", [], []))


SEPARATOR_TEXTS = (
    "waiting — check: retry later",
    "db down — owner: reviewer — after: T2",
    "see `a.py` — files: `b.py` — evidence: none",
)


def error_codes(plan) -> set:
    return {f.code for f in checks.run_checks(plan, "draft") if f.severity == "error"}


class FreeTextFieldTest(unittest.TestCase):
    """G4 F7: blocked and evidence are free text; a ` — key: ` inside them never starts a field."""

    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_block_reason_with_separators(self) -> None:
        base = fixture_text("base-ok")
        inline = T1_HEAD.replace(" — files:", " — blocked: old note — files:", 1)
        starts = {"inline blocked": replace_once(base, T1_HEAD + "\n", inline + "\n"), "no blocked": base}
        for label, start in starts.items():
            for reason in SEPARATOR_TEXTS:
                with self.subTest(head=label, reason=reason):
                    blocked = mutate.node_command(self.repo.parse("base-ok", start), "block", "T1", mutate.NodeOptions(reason=reason), AT)
                    rendered = blocked.plan_bytes.decode("utf-8")
                    self.assertIn(T1_HEAD.replace("- [ ]", "- [!]", 1) + f"\n  - blocked: {reason}\n", rendered)
                    node = blocked.plan.node("T1")
                    self.assertEqual((node.mark, node.title, node.writes, node.issues), ("!", "Add the greet command", T1_WRITES, []))
                    self.assertEqual((node.fields["blocked"], node.fields["check"]), (reason, "`pytest tests/test_greet.py`"))
                    self.assertEqual(set(node.fields), {"writes", "check", "blocked"})
                    self.assertEqual(error_codes(blocked.plan), set())
                    reset = mutate.node_command(blocked.plan, "reset", "T1", mutate.NodeOptions(), AT)
                    self.assertEqual(reset.plan_bytes.decode("utf-8"), base)

    def test_block_reason_on_a_node_with_field_lines(self) -> None:
        base = fixture_text("team-ok")
        for reason in SEPARATOR_TEXTS:
            with self.subTest(reason=reason):
                blocked = mutate.node_command(self.repo.parse("team-ok", base), "block", "N1", mutate.NodeOptions(reason=reason), AT)
                node = blocked.plan.node("N1")
                self.assertEqual((node.owner, node.after, node.writes, node.scenarios, node.issues), ("implementer", [], ["src/csv/**", "tests/csv/**"], ["AT-02"], []))
                self.assertEqual((node.fields["blocked"], node.fields["check"]), (reason, "`pytest tests/csv`"))
                self.assertEqual(error_codes(blocked.plan), set())
                reset = mutate.node_command(blocked.plan, "reset", "N1", mutate.NodeOptions(), AT)
                self.assertEqual(reset.plan_bytes.decode("utf-8"), base)

    def test_done_evidence_with_separators(self) -> None:
        for slug, node_id in (("base-ok", "T1"), ("team-ok", "N1")):
            for text in SEPARATOR_TEXTS:
                with self.subTest(plan=slug, evidence=text):
                    plan = self.repo.parse(slug, fixture_text(slug))
                    before = plan.node(node_id)
                    done = mutate.node_command(plan, "done", node_id, mutate.NodeOptions(evidence=text), AT)
                    node = done.plan.node(node_id)
                    self.assertEqual((node.mark, node.evidence, node.issues), ("x", [text], []))
                    self.assertEqual({k: v for k, v in node.fields.items() if k != "evidence"}, before.fields)
                    self.assertEqual(error_codes(done.plan), set())



class ApplyTest(unittest.TestCase):
    """G2 F1: apply checks every destination before it writes anything."""

    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.close)

    def test_state_path_taken_after_the_change_was_built(self) -> None:
        path = self.repo.write_plan("workflow-ok", fixture_text("workflow-ok"))
        change = mutate.advance(planfile.parse_plan(self.repo.root, path), "approved", AT)
        self.assertIsNotNone(change.plan_bytes)
        state_path = self.repo.root / "plan" / "workflow-ok.state.json"
        state_path.mkdir()
        before = path.read_bytes()
        with self.assertRaises(mutate.Refused) as caught:
            mutate.apply(change)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("is not a regular file", str(caught.exception))
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(state_path.is_dir())


if __name__ == "__main__":
    unittest.main()
