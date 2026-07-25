"""Tests for temporal/taskauto/plan_notes.py.

The round-trip tests matter most: the human edits a document we wrote, and
we have to read our own structure back out of whatever they hand us without
losing their reply.
"""

from __future__ import annotations

import pytest

from temporal.taskauto.plan_notes import (
    MAX_PASSES,
    PlanDoc,
    looks_unplanned,
    parse,
    render,
)


def sample() -> PlanDoc:
    return PlanDoc(
        understanding="deploy.yml fails on the pnpm provisioning step.",
        plan=["Pin pnpm via corepack", "Re-run the failing workflow"],
        questions=["Should this also cover the temporal worker deploy?"],
        settled=[("Which repo?", "tenhands")],
        acceptance=["deploy.yml completes green on main"],
        blast_radius=[".github/workflows/deploy.yml"],
        pass_number=2,
        confidence=0.8,
    )


# ── render ────────────────────────────────────────────────────────────────


def test_render_includes_every_populated_section():
    out = render(sample())
    for heading in ("## What I think you want", "## Plan", "## Questions",
                    "## Settled", "## How we'll know it worked",
                    "## Blast radius"):
        assert heading in out
    assert "— pass 2 · confidence 0.8" in out


def test_render_omits_empty_sections_but_always_states_questions():
    """'Nothing is being asked of me' is the one thing the reader most wants
    to know; its absence would be ambiguous with a truncated document."""
    out = render(PlanDoc(understanding="just do it", pass_number=1))
    assert "## Plan" not in out
    assert "## Blast radius" not in out
    assert "## Questions" in out and "_No open questions._" in out


def test_render_omits_confidence_when_unknown():
    out = render(PlanDoc(pass_number=1))
    assert "— pass 1" in out and "confidence" not in out


def test_render_numbers_plan_and_questions_but_bullets_the_rest():
    out = render(sample())
    assert "1. Pin pnpm via corepack" in out
    assert "1. Should this also cover" in out
    assert "- .github/workflows/deploy.yml" in out


def test_render_is_stable_across_calls():
    """The document is rewritten every pass; churn would make the board look
    busy when nothing changed."""
    assert render(sample()) == render(sample())


# ── round trip ────────────────────────────────────────────────────────────


def test_round_trip_preserves_structure():
    doc = parse(render(sample()))
    original = sample()
    assert doc.understanding == original.understanding
    assert doc.plan == original.plan
    assert doc.questions == original.questions
    assert doc.settled == original.settled
    assert doc.acceptance == original.acceptance
    assert doc.blast_radius == original.blast_radius
    assert doc.pass_number == 2
    assert doc.confidence == 0.8
    assert doc.human_text == ""


def test_round_trip_of_a_no_questions_document():
    doc = parse(render(PlanDoc(plan=["do it"], pass_number=1)))
    assert doc.questions == []
    assert doc.has_open_questions is False


# ── the human's reply ─────────────────────────────────────────────────────


def test_reply_dumped_at_the_top_is_captured_not_lost():
    """Someone typing on a bus will not respect our section layout."""
    notes = "yes do the worker too\n\n" + render(sample())
    doc = parse(notes)
    assert "yes do the worker too" in doc.human_text
    assert doc.plan == sample().plan, "our structure still parses"


def test_reply_under_an_invented_heading_is_captured():
    notes = render(sample()) + "\n\n## My answer\n\nuse corepack, not volta\n"
    doc = parse(notes)
    assert "use corepack, not volta" in doc.human_text
    assert "My answer" in doc.human_text


def test_an_inline_answer_stays_attached_to_its_question():
    """Answering under the question is the most natural way to reply, and
    an earlier version dropped those lines entirely — they appeared in
    neither `questions` nor `human_text`. Keeping the answer joined to the
    question also preserves which question it answers, which a flat
    residue bucket would lose."""
    notes = render(PlanDoc(
        questions=["Cover the worker too?"], pass_number=1))
    notes = notes.replace("1. Cover the worker too?",
                          "1. Cover the worker too?\n   yes, please")
    doc = parse(notes)
    assert doc.questions == ["Cover the worker too?\nyes, please"]


def test_an_unindented_reply_in_a_section_becomes_human_text():
    notes = render(PlanDoc(questions=["Cover the worker too?"], pass_number=1))
    notes = notes.replace("1. Cover the worker too?",
                          "1. Cover the worker too?\nyes do it")
    doc = parse(notes)
    assert doc.questions == ["Cover the worker too?"]
    assert "yes do it" in doc.human_text


def test_a_reply_under_no_open_questions_is_kept():
    notes = render(PlanDoc(plan=["x"], pass_number=1)).replace(
        "_No open questions._", "_No open questions._\n\nactually, wait")
    assert "actually, wait" in parse(notes).human_text


@pytest.mark.parametrize("reply", [
    "yes do the worker too",
    "no — use volta instead",
    "?",
])
def test_no_human_text_is_ever_silently_dropped(reply):
    """The invariant this module exists to hold. Wherever the human types,
    their words come back out somewhere we can hand to the planning agent."""
    base = render(sample())
    for notes in (
        reply + "\n\n" + base,                                  # above
        base + "\n\n" + reply,                                  # below
        base.replace("## Plan", reply + "\n\n## Plan"),         # mid-doc
        base.replace("## Blast radius\n", "## Blast radius\n" + reply + "\n"),
    ):
        doc = parse(notes)
        # `understanding` counts: text typed just above "## Plan" falls
        # inside that section's body. It isn't lost — the planning agent
        # reads understanding every pass — it just isn't in `human_text`.
        haystack = doc.human_text + doc.understanding + "\n".join(
            doc.questions + doc.plan + doc.blast_radius + doc.acceptance)
        assert reply in haystack, f"lost {reply!r} from:\n{notes}"


def test_duplicated_section_is_kept_as_human_text():
    """A human pasting a second '## Plan' is editing by duplication. The
    second copy could hold their answer, so it must not be dropped."""
    notes = render(sample()) + "\n\n## Plan\n\n- actually do it this way\n"
    doc = parse(notes)
    assert doc.plan == sample().plan
    assert "actually do it this way" in doc.human_text


def test_footer_is_not_left_in_human_text():
    doc = parse(render(sample()))
    assert "pass 2" not in doc.human_text


# ── robustness ────────────────────────────────────────────────────────────


def test_parse_of_raw_capture_is_all_human_text():
    doc = parse("reorganize categories, interesting stuff front and center")
    assert doc.plan == [] and doc.questions == []
    assert "reorganize categories" in doc.human_text


def test_parse_of_empty_notes():
    doc = parse("")
    assert doc.pass_number == 1 and doc.human_text == ""
    assert doc.has_open_questions is False


def test_parse_never_raises_on_mangled_input():
    """A human can mangle the document arbitrarily. Failing a workflow over
    markdown would be a bad trade."""
    for junk in ("## \n\n", "###### Plan", "— pass banana", "## Plan\n\n",
                 "— pass 2 · confidence not-a-number", "\x00\x01"):
        parse(junk)


def test_unparseable_footer_falls_back_to_pass_one():
    assert parse("— pass banana").pass_number == 1


def test_bad_confidence_is_dropped_not_fatal():
    doc = parse("## Plan\n\n- x\n\n— pass 2 · confidence not-a-number")
    assert doc.pass_number == 2 and doc.confidence is None


def test_none_placeholder_is_read_as_empty():
    doc = parse("## Blast radius\n\n_none_\n")
    assert doc.blast_radius == []


def test_settled_accepts_both_arrow_forms():
    doc = parse("## Settled\n\n- Which repo? → tenhands\n- Which branch? -> main\n")
    assert doc.settled == [("Which repo?", "tenhands"),
                           ("Which branch?", "main")]


def test_settled_without_an_arrow_keeps_the_question():
    doc = parse("## Settled\n\n- something the human typed\n")
    assert doc.settled == [("something the human typed", "")]


# ── loop control ──────────────────────────────────────────────────────────


def test_pass_cap():
    assert PlanDoc(pass_number=MAX_PASSES).at_pass_cap is True
    assert PlanDoc(pass_number=MAX_PASSES - 1).at_pass_cap is False
    assert PlanDoc(pass_number=1).next_pass() == 2


def test_looks_unplanned_distinguishes_capture_from_a_plan():
    """Without this the runner would treat a brand-new task as a stalled
    conversation."""
    assert looks_unplanned("too much wooshing") is True
    assert looks_unplanned("") is True
    assert looks_unplanned(render(sample())) is False


def test_a_plan_with_no_questions_still_counts_as_planned():
    assert looks_unplanned(render(PlanDoc(plan=["x"], pass_number=1))) is False


@pytest.mark.parametrize("n", [1, 2, 3])
def test_pass_number_survives_the_round_trip(n):
    assert parse(render(PlanDoc(pass_number=n))).pass_number == n
