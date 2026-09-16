"""The task-list half of the plan format, pinned against hadoku-task's copy.

**These are transcribed fixtures, not invented ones.** Every case in
`TestMirrorsHadokuTask` is the same input and the same expectation as
`src/test/plan-notes-verify.ts` in hadoku-task, case for case and string for
string. That is the point of the file: the board fires our runner wake on
*their* `questionsAnswered`, and we decide what to do on *ours*, so the two
predicates answering differently is a live failure mode rather than a tidiness
concern.

Keep them in step by editing both, and keep the fixtures byte-identical — a
case that has been "tidied up" on one side is a case that no longer compares
anything.

A disagreement degrades rather than corrupts (we get woken and find nothing to
do, or we find it a sweep later), which is why this is a test rather than a
runtime assertion. It is still two answers to one question.
"""

from __future__ import annotations

import pytest

from temporal.taskauto import plan_notes
from temporal.taskauto.plan_notes import (
    APPROVAL_ITEM,
    PlanDoc,
    checklist_items,
    open_question_count,
    pending_approval,
    questions_answered,
    render,
)


# ── 1. Plans with no checkboxes behave exactly as before ──────────────────

ASKED = "## Questions\n\n- Should the TTL apply to negative lookups too?\n- Which branch?\n"
REPLIED = ASKED + "\nYes to both, use main.\n"
IMPERATIVE = "## Questions\n\n- Confirm the repo.\n- Name the branch.\n"
SENTINEL = "## Questions\n\n_No open questions._\n"
NO_SECTION = "## Plan\n\nDo the thing.\n"

# ── 2. An unticked box is an open ask; a ticked one is its own answer ─────

ONLY = "## Questions\n\n- [ ] Approve this plan\n"
TICKED = "## Questions\n\n- [x] Approve this plan\n"
MIXED = ("## Questions\n\n- Should the TTL apply to negative lookups too?\n"
         "- [ ] Approve this plan\n")
REPLIED_ONLY = MIXED + "\nYes, negative lookups too.\n"
BOTH = ("## Questions\n\n- Should the TTL apply to negative lookups too?\n"
        "- [x] Approve this plan\n\nYes, negative lookups too.\n")
TICKED_NO_REPLY = ("## Questions\n\n- Should the TTL apply to negative lookups too?\n"
                   "- [x] Approve this plan\n")

FENCED = "\n".join([
    "## Plan",
    "",
    "- [x] Already done",
    "",
    "```markdown",
    "- [ ] this is an EXAMPLE, not a control",
    "```",
    "",
    "## Questions",
    "",
    "- [ ] Approve this plan",
])


class TestMirrorsHadokuTask:
    """Case for case with `src/test/plan-notes-verify.ts`."""

    @pytest.mark.parametrize("notes,expected", [
        (ASKED, 2),           # two questions with `?` count two
        (REPLIED, 0),         # a trailing reply takes the count to 0
        (IMPERATIVE, 2),      # no `?` anywhere ⇒ every item counts
        (SENTINEL, 0),        # the sentinel is 0
        (NO_SECTION, 0),      # no Questions section at all is 0
        (ONLY, 1),            # a lone unticked box counts 1
        (TICKED, 0),          # ticking it takes the count to 0
        (MIXED, 2),           # a `?` question plus an unticked box counts both
        (REPLIED_ONLY, 1),    # replying leaves the box outstanding
        (BOTH, 0),            # reply + tick clears the count
    ])
    def test_open_question_count(self, notes, expected):
        assert open_question_count(notes) == expected

    @pytest.mark.parametrize("notes,expected", [
        (ASKED, False),
        (REPLIED, True),
        (SENTINEL, False),
        (NO_SECTION, False),
        (ONLY, False),
        (TICKED, True),       # …and THAT is what fires the wake
        (MIXED, False),
        (REPLIED_ONLY, False),  # NOT answered — this is "send it back"
        (BOTH, True),
        (TICKED_NO_REPLY, False),  # ticking with a question still open
    ])
    def test_questions_answered(self, notes, expected):
        assert questions_answered(notes) is expected

    def test_a_box_inside_a_fence_is_text(self):
        assert [i.text for i in checklist_items(FENCED)] == [
            "Already done", "Approve this plan"]

    def test_ordinals_run_in_document_order(self):
        assert [(i.ordinal, i.checked) for i in checklist_items(FENCED)] == [
            (0, True), (1, False)]

    def test_pending_approval_finds_the_unticked_one(self):
        found = pending_approval(FENCED)
        assert found is not None and found.ordinal == 1

    def test_pending_approval_skips_a_ticked_one(self):
        assert pending_approval("- [x] Approve this plan") is None

    def test_pending_approval_skips_a_non_approval_box(self):
        assert pending_approval("- [ ] Write the tests") is None


class TestRendering:
    """Our half — the document we emit has to satisfy the predicates above."""

    def test_an_approval_plan_is_not_answered_until_it_is_ticked(self):
        notes = render(PlanDoc(understanding="Cache the lookups.",
                               plan=["Add a TTL."], needs_approval=True))
        assert APPROVAL_ITEM in notes
        assert questions_answered(notes) is False
        assert open_question_count(notes) == 1
        assert pending_approval(notes) is not None

    def test_ticking_our_rendered_row_answers_it(self):
        notes = render(PlanDoc(understanding="Cache the lookups.",
                               needs_approval=True))
        ticked = notes.replace(APPROVAL_ITEM, "- [x] Approve this plan")
        assert questions_answered(ticked) is True
        assert pending_approval(ticked) is None

    def test_questions_and_approval_render_together(self):
        notes = render(PlanDoc(questions=["Which branch?"],
                               needs_approval=True))
        assert open_question_count(notes) == 2
        # The approval row goes last: it is the decision the section leads up
        # to, and on a phone that belongs nearest the thumb.
        assert notes.index(APPROVAL_ITEM) > notes.index("Which branch?")

    def test_awaiting_approval_never_renders_the_sentinel(self):
        """The trap: `_No open questions._` reads as "asks nothing" to BOTH
        parsers, so a plan that rendered it while awaiting sign-off could
        never be approved and would never report why."""
        notes = render(PlanDoc(understanding="x", needs_approval=True))
        assert "_No open questions._" not in notes
        assert open_question_count(notes) == 1

    def test_a_plan_asking_nothing_still_renders_the_sentinel(self):
        notes = render(PlanDoc(understanding="x", needs_approval=False))
        assert "_No open questions._" in notes
        assert open_question_count(notes) == 0


class TestRoundTrip:
    """`parse` has to agree with the predicates about the same document."""

    def test_a_ticked_approval_is_not_a_question_we_are_still_asking(self):
        doc = plan_notes.parse(TICKED)
        assert doc.questions == []
        assert doc.has_open_questions is False

    def test_an_unticked_approval_still_reads_as_an_open_question(self):
        doc = plan_notes.parse(ONLY)
        assert doc.has_open_questions is True

    def test_a_trailing_reply_reaches_human_text(self):
        doc = plan_notes.parse(REPLIED)
        assert "Yes to both, use main." in doc.human_text

    def test_a_reply_is_trailing_prose_not_any_prose(self):
        """`_bullets` called every non-bullet line residue wherever it sat, so
        a paragraph written ABOVE the questions read as an answer to them."""
        preamble = ("## Questions\n\nSome context I typed first.\n\n"
                    "- Which branch?\n")
        assert questions_answered(preamble) is False
        assert open_question_count(preamble) == 1

    def test_a_retitled_questions_heading_is_still_the_questions_section(self):
        """Their `isQuestionsHeading` tolerates this and ours used not to —
        which mattered once the wake started firing on their reading."""
        assert open_question_count("## Open questions\n\n- Which branch?\n") == 1
        assert questions_answered("## Questions:\n\n- [x] Approve this\n") is True


# ── The footer, and the reply that lands after it ─────────────────────────
#
# hadoku-task shipped this defect in their copy of the format on 2026-09-15:
# `parsePlanNotes` had no concept of our `— pass N` footer, so on any plan
# whose last section is `## Questions` it read the footer as the human's
# reply, and the wake for an actual reply then never fired. Fixed their side
# in 13b862a.
#
# They asked us to check the mirror image, and they were right to: their
# `appendAnswerToNotes` puts a reply AFTER our footer when Questions is last,
# so a strip anchored to the final line would stop working at exactly the
# moment someone answers. Ours is a `sub`, so it holds — these pin that, using
# their fixture verbatim.

#: What a Questions-last plan looks like once answered through their UI.
REPLY_AFTER_FOOTER = (
    "## Questions\n\n- Which branch should this land on?\n\n"
    "— pass 2 · confidence 0.8\n\nLand it on main.\n")


class TestTheFooterIsNeverTheHumansReply:
    def test_a_reply_after_the_footer_still_reads_as_a_reply(self):
        assert questions_answered(REPLY_AFTER_FOOTER) is True
        assert open_question_count(REPLY_AFTER_FOOTER) == 0

    def test_the_footer_does_not_reach_the_planner_as_human_text(self):
        doc = plan_notes.parse(REPLY_AFTER_FOOTER)
        assert doc.human_text == "Land it on main."
        assert "pass 2" not in doc.human_text

    def test_a_footer_that_is_not_last_is_still_read(self):
        doc = plan_notes.parse(REPLY_AFTER_FOOTER)
        assert doc.pass_number == 2 and doc.confidence == 0.8

    def test_an_unanswered_questions_last_plan_is_not_answered(self):
        """The defect itself, from their side. Our own footer must not close
        our own question."""
        notes = render(PlanDoc(questions=["Which branch?"], pass_number=1))
        assert notes.rstrip().endswith("— pass 1")
        assert questions_answered(notes) is False
        assert open_question_count(notes) == 1

    def test_the_sentinel_survives_its_own_footer(self):
        notes = render(PlanDoc(understanding="u", pass_number=1))
        assert "_No open questions._" in notes
        assert questions_answered(notes) is False
        assert open_question_count(notes) == 0


class TestTheFooterPatternIsTightOnStructureNotValues:
    """Permissive on the VALUES on purpose — a strict `[0-9.]+` once made the
    whole footer fail to match on junk confidence, which silently reset
    `pass_number` to 1 and let the planning loop run past its cap. Tight on
    the SHAPE, so a human's prose that happens to start the same way is their
    text and not our bookkeeping."""

    @pytest.mark.parametrize("line", [
        "— pass 2",
        "— pass 2 · confidence 0.8",
        "— pass ? · confidence junk",
    ])
    def test_ours_is_stripped(self, line):
        assert plan_notes._FOOTER_RE.fullmatch(line)

    @pytest.mark.parametrize("line", [
        "— pass the buck to legal",
        "— pass 2 extra words",
    ])
    def test_a_humans_sentence_is_not(self, line):
        assert not plan_notes._FOOTER_RE.fullmatch(line)


class TestWhichFooterIsAuthoritative:
    """`with_trailing_note` has always documented the convention — "the LAST
    footer: a human may have pasted an older one above" — and `parse` used
    `search`, which takes the first. They disagreed, and the disagreement ran
    the pass counter BACKWARDS: a pasted `— pass 1` above ours made a third
    pass report as its first, uncapping the planning loop."""

    PASTED = ("## Questions\n\n- Which branch?\n\n"
              "— pass 1\n\nsome context\n\n— pass 3\n")

    def test_the_last_footer_wins(self):
        assert plan_notes.parse(self.PASTED).pass_number == 3

    def test_that_is_the_footer_with_trailing_note_writes_before(self):
        after = plan_notes.with_trailing_note(self.PASTED, "NOTE")
        assert after.split("NOTE")[1].strip().startswith("— pass 3")

    def test_neither_footer_reaches_the_planner(self):
        text = plan_notes.parse(self.PASTED).human_text
        assert "pass 1" not in text and "pass 3" not in text
        assert "some context" in text
