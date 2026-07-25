"""The plan document that lives in a task's `notes`.

`notes` is the medium for the whole planning conversation: we write a plan
and questions, the human answers, we re-plan, until nobody has an open
question. Two properties matter more than the format itself.

**We rewrite, never append.** Three rounds of plan-then-answer appended would
become something nobody reads on a phone, and would eventually approach the
64 KiB cap. Each pass re-emits one canonical document; history lives in the
evidence store and the board's claim log, which are the right places for it.

**We parse what we wrote and pass through what we didn't.** The human answers
however they like — inline under Questions, or a sentence dumped at the top.
Demanding a format from someone typing on a bus would defeat the point. So
this module extracts the parts we control and hands everything else back
verbatim as `human_text`, for the planning agent to interpret. Deciding what
a human meant is a language problem, not a parsing one, and pretending
otherwise would produce a parser that is confidently wrong.

Note the deliberate asymmetry: `notes` is *not* a source of authorisation.
See `task_text.extract_allow_protected` for why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

#: Cap on planning round-trips before a task is stalled for a human. Three
#: passes that haven't converged usually means the task needs a laptop, not
#: a fourth round of questions.
MAX_PASSES = 3

H_UNDERSTANDING = "What I think you want"
H_PLAN = "Plan"
H_QUESTIONS = "Questions"
H_SETTLED = "Settled"
H_ACCEPTANCE = "How we'll know it worked"
H_BLAST = "Blast radius"

_KNOWN_HEADINGS = (
    H_UNDERSTANDING, H_PLAN, H_QUESTIONS, H_SETTLED, H_ACCEPTANCE, H_BLAST,
)

_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)
# The confidence group is deliberately permissive (`\S+`, validated after
# matching) rather than `[0-9.]+`. A strict pattern made the WHOLE footer
# fail to match on junk confidence, silently resetting pass_number to 1 —
# which would restart the planning loop and let it run past its cap.
_FOOTER_RE = re.compile(
    r"^—\s*pass\s+(?P<pass>\S+)(?:\s*·\s*confidence\s+(?P<conf>\S+))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(?P<text>.+?)\s*$")


@dataclass
class PlanDoc:
    """One pass of the planning conversation."""

    understanding: str = ""
    plan: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    #: Answered questions, as (question, answer) — echoed back so the human
    #: can see their earlier replies were heard rather than re-litigated.
    settled: list[tuple[str, str]] = field(default_factory=list)
    #: Observable end conditions. G2 requires at least one for a change
    #: request; for a `bug-` item the reproduction plays this role.
    acceptance: list[str] = field(default_factory=list)
    blast_radius: list[str] = field(default_factory=list)
    pass_number: int = 1
    confidence: Optional[float] = None
    #: Anything in `notes` that isn't a section we emit — usually the human's
    #: reply. Never interpreted here; handed to the planning agent as-is.
    human_text: str = ""

    @property
    def has_open_questions(self) -> bool:
        return bool(self.questions)

    @property
    def at_pass_cap(self) -> bool:
        return self.pass_number >= MAX_PASSES

    def next_pass(self) -> int:
        return self.pass_number + 1


def _render_list(items: list[str], *, numbered: bool = False) -> str:
    if not items:
        return "_none_"
    if numbered:
        return "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))
    return "\n".join(f"- {t}" for t in items)


def render(doc: PlanDoc) -> str:
    """Render the canonical document a human reads on their phone.

    Sections are omitted when empty rather than shown as empty, except
    Questions — an explicit "no open questions" is worth a line, because
    "nothing is being asked of me" is the single thing the reader most
    wants to know, and its absence would be ambiguous with a truncated doc.
    """
    parts: list[str] = []

    if doc.understanding:
        parts.append(f"## {H_UNDERSTANDING}\n\n{doc.understanding.strip()}")

    if doc.plan:
        parts.append(f"## {H_PLAN}\n\n{_render_list(doc.plan, numbered=True)}")

    if doc.questions:
        parts.append(
            f"## {H_QUESTIONS}\n\n"
            f"{_render_list(doc.questions, numbered=True)}"
        )
    else:
        parts.append(f"## {H_QUESTIONS}\n\n_No open questions._")

    if doc.settled:
        lines = "\n".join(f"- {q} → {a}" for q, a in doc.settled)
        parts.append(f"## {H_SETTLED}\n\n{lines}")

    if doc.acceptance:
        parts.append(f"## {H_ACCEPTANCE}\n\n{_render_list(doc.acceptance)}")

    if doc.blast_radius:
        parts.append(f"## {H_BLAST}\n\n{_render_list(doc.blast_radius)}")

    footer = f"— pass {doc.pass_number}"
    if doc.confidence is not None:
        footer += f" · confidence {doc.confidence:g}"
    parts.append(footer)

    return "\n\n".join(parts).strip() + "\n"


def _sections(text: str) -> tuple[dict[str, str], str]:
    """Split into {heading: body} plus everything outside a known heading."""
    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return {}, text.strip()

    loose = [text[: matches[0].start()]]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        title = m.group("title").strip()
        if title in _KNOWN_HEADINGS:
            # A repeated heading means the human duplicated a section rather
            # than editing in place. Keep the first and treat the rest as
            # their text — dropping it could lose an answer.
            if title in sections:
                loose.append(f"## {title}\n{body}")
            else:
                sections[title] = body
        else:
            loose.append(f"## {title}\n{body}")
    return sections, "\n\n".join(p.strip() for p in loose if p.strip()).strip()


def _bullets(body: str) -> tuple[list[str], str]:
    """Split a section body into its bullets and everything else.

    Two rules, both there to guarantee the invariant that **no text a human
    typed is ever silently dropped**:

    - An indented line following a bullet is a continuation and joins it.
      That's how someone answers inline — writing under the question — and
      it keeps the answer attached to the question it answers.
    - Anything else is residue, returned to the caller for `human_text`.

    An earlier version returned only regex matches, which discarded inline
    answers entirely: they appeared in neither `questions` nor `human_text`.
    The human's reply is the one thing this module exists to carry.
    """
    if not body or body.strip() == "_none_":
        return [], ""

    items: list[str] = []
    residue: list[str] = []
    for line in body.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            text = m.group("text").strip()
            if text:
                items.append(text)
            continue
        if not line.strip():
            continue
        if items and (line[:1].isspace()):
            items[-1] = f"{items[-1]}\n{line.strip()}"
            continue
        residue.append(line.strip())
    return items, "\n".join(residue)


def parse(text: str) -> PlanDoc:
    """Best-effort read of a notes field.

    Never raises. A human may have mangled the document arbitrarily, and the
    correct response to that is to recover what we can and let the planning
    agent read the rest — not to fail a workflow over markdown.
    """
    text = text or ""

    doc = PlanDoc()

    # Pull the footer out FIRST. It trails the last section, so sectioning
    # first would fold it into that section's body and then surface it as
    # residue in `human_text` — the planning agent would read our own
    # bookkeeping back as if the human had typed it.
    m = _FOOTER_RE.search(text)
    if m:
        try:
            doc.pass_number = int(m.group("pass"))
        except (TypeError, ValueError):
            doc.pass_number = 1
        if m.group("conf"):
            try:
                doc.confidence = float(m.group("conf"))
            except (TypeError, ValueError):
                doc.confidence = None
        text = _FOOTER_RE.sub("", text)

    sections, loose = _sections(text)
    residues: list[str] = []

    def section(name: str) -> list[str]:
        items, residue = _bullets(sections.get(name, ""))
        if residue:
            residues.append(residue)
        return items

    doc.understanding = sections.get(H_UNDERSTANDING, "").strip()
    doc.plan = section(H_PLAN)
    doc.acceptance = section(H_ACCEPTANCE)
    doc.blast_radius = section(H_BLAST)

    questions_body = sections.get(H_QUESTIONS, "")
    if questions_body.strip().lower().startswith("_no open questions"):
        doc.questions = []
        # A human who answered by typing under "_No open questions._" still
        # said something; keep it.
        extra = questions_body.strip().split("\n", 1)
        if len(extra) > 1 and extra[1].strip():
            residues.append(extra[1].strip())
    else:
        doc.questions = section(H_QUESTIONS)

    for line in section(H_SETTLED):
        q, sep, a = line.partition("→")
        if not sep:
            q, sep, a = line.partition("->")
        if sep:
            doc.settled.append((q.strip(), a.strip()))
        else:
            doc.settled.append((line.strip(), ""))

    doc.human_text = "\n\n".join(
        p for p in ([loose] + residues) if p.strip()).strip()
    return doc


def looks_unplanned(text: str) -> bool:
    """True when `notes` has never held one of our documents.

    Raw capture — the human's own words, or nothing at all. Distinguishing
    this from a plan awaiting answers is what stops the runner treating a
    first-time task as a stalled conversation.
    """
    doc = parse(text)
    return not (doc.understanding or doc.plan or doc.questions or doc.settled)
