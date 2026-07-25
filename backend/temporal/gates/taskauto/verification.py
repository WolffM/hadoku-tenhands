"""G2 — `verification_possible`.

Runs at the end of planning, before a single implementation token is spent.

If nothing distinguishes the before state from the after state, then a green
suite afterwards is evidence of nothing at all — it was green before. This
gate is what makes "lands on green" mean something.

What counts as verifiable depends on which kind of item this is, and the
human's own title already says. An earlier draft demanded a reproduction
from *everything*, which would have stalled `make coffee theme default`
forever: nothing is claimed broken, so there is no red state to reach.
Demanding one is a category error, not a strict standard.
"""

from __future__ import annotations

from .. import TASK_AUTOMATION, Fail, GateResult, Pass, gate
from ...taskauto import plan_notes
from ...taskauto.task_text import classify

#: Where the planning stage writes the document it also put in `notes`.
PLAN_PATH = "10-planned/plan.md"


@gate(pipeline=TASK_AUTOMATION, after="planned", kind="mechanical")
def verification_possible(task, evidence) -> GateResult:
    """Fail when there is no way to tell whether the work succeeded."""
    try:
        raw = evidence.read_text(PLAN_PATH)
    except Exception as e:
        return Fail(f"could not read {PLAN_PATH}: {type(e).__name__}: {e}")

    doc = plan_notes.parse(raw or "")
    kind = classify(getattr(task, "title", "") or "")

    if doc.has_open_questions:
        # Not a verification problem — the plan simply isn't finished. Say
        # so distinctly, because "I still have questions" and "there's no way
        # to check this" send the human to very different places.
        return Fail(
            f"{len(doc.questions)} question(s) still open; not ready to verify",
            evidence_data={"questions": doc.questions},
        )

    if kind.is_bug:
        if not doc.acceptance:
            return Fail(
                "a `bug-` task needs a reproduction: what shows this is "
                "broken today? Without a red artifact, a green suite after "
                "the fix proves nothing.",
                evidence_data={"kind": "bug"},
            )
        return Pass(
            f"bug with {len(doc.acceptance)} reproduction/acceptance item(s)",
            evidence_data={"kind": "bug", "acceptance": doc.acceptance},
        )

    if not doc.acceptance:
        return Fail(
            "a change request needs an acceptance check: what observable "
            "end state means this is done? Ask the human how they would "
            "tell that it was fixed — their answer becomes the check.",
            evidence_data={"kind": "change"},
        )
    return Pass(
        f"change request with {len(doc.acceptance)} acceptance check(s)",
        evidence_data={"kind": "change", "acceptance": doc.acceptance},
    )
