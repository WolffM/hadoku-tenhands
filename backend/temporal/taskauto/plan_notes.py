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

H_OUTCOME = "Outcome"
H_UNDERSTANDING = "What I think you want"
H_PLAN = "Plan"
H_QUESTIONS = "Questions"
H_SETTLED = "Settled"
H_ACCEPTANCE = "How we'll know it worked"
H_BLAST = "Blast radius"

_KNOWN_HEADINGS = (
    H_OUTCOME, H_UNDERSTANDING, H_PLAN, H_QUESTIONS, H_SETTLED, H_ACCEPTANCE,
    H_BLAST,
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

# ── Task-list items: the approval channel ─────────────────────────────────
#
# Everything below mirrors `src/domain/planNotes.ts` in hadoku-task, and has
# to keep mirroring it. The board fires the runner wake on THEIR
# `questionsAnswered`; we decide what to do on OURS. A disagreement degrades
# rather than corrupts — we get woken and find nothing, or we find it a sweep
# later — but it is still two answers to one question, so the rules are
# transcribed rather than reinvented.

#: `- [ ] text` / `- [x] text`, GitHub-flavoured. Mirrors their `TASK_ITEM`.
_TASK_ITEM_RE = re.compile(
    r"^(?P<prefix>\s*(?:[-*+]|\d+[.)])\s+\[)(?P<box>[ xX])(?P<gap>\]\s*)"
    r"(?P<text>.*)$")

#: ``` or ~~~ opening or closing a fenced block. A `- [ ]` inside one is an
#: example, not a control — the same rule their parser applies to headings.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

#: An approval row is a task-list item whose text starts with "Approve".
#: Matched on the leading word only and case-insensitively, so the wording
#: after it stays ours to change without a coordinated release.
_APPROVAL_RE = re.compile(r"^approve\b", re.IGNORECASE)

#: The approval row we emit. `pending_approval` on both sides matches the
#: leading word structurally, so the wording after "Approve" is ours to change
#: without a coordinated release — but only this constant should ever write it.
APPROVAL_ITEM = "- [ ] Approve this plan"

#: A `_bullets` item that was a task-list row before its marker was stripped.
#: `_bullets` hands back `[ ] Approve this plan`, which `_TASK_ITEM_RE` no
#: longer matches because the marker is gone — so the two see checkboxes
#: through different windows and each needs its own.
_CHECKBOX_TEXT_RE = re.compile(r"^\[[ xX]\]\s*")


def _task_item_state(item: str) -> Optional[bool]:
    """Tick state of a list item, or None when it isn't a task-list item.

    None is the load-bearing case: it is what keeps every prose question
    counting exactly as it did before task lists existed.
    """
    m = _TASK_ITEM_RE.match(item)
    return None if m is None else m.group("box") != " "


@dataclass
class PlanDoc:
    """One pass of the planning conversation."""

    #: What happened *to* the task — merged, opened as a PR, verified-not-pushed.
    #: Distinct from `understanding` (what the task is *for*): a status line under
    #: "What I think you want" reads as nonsense once a task is done, so a
    #: terminal/in-flight state gets its own heading and the understanding is
    #: free to keep meaning what it says.
    outcome: str = ""
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
    #: Ask the human to sign the plan off before it is implemented.
    #:
    #: Renders as `- [ ] Approve this plan` at the end of `## Questions`, which
    #: is the whole of the approval mechanism — there is no approvals table and
    #: no `metadata.approved`. Ticking the box is the sign-off, and because it
    #: is an unticked task-list item it also keeps `questions_answered` false
    #: until it is ticked, so the plan cannot be read as settled while it is
    #: still waiting on a decision.
    #:
    #: In v1/v2 this was a lane to drag to. It is a row in the document now
    #: because with lanes carrying repos there is no second tag to spend on it.
    needs_approval: bool = False
    pass_number: int = 1
    confidence: Optional[float] = None
    #: Anything in `notes` that isn't a section we emit — usually the human's
    #: reply. Never interpreted here; handed to the planning agent as-is.
    human_text: str = ""

    @property
    def has_open_questions(self) -> bool:
        """Is anything still being asked of the human?

        An unticked approval row counts. It is the one thing a plan can be
        waiting on with `questions` empty, and the verification gate reads this
        to decide whether the conversation is settled enough to verify — a plan
        that is merely unsigned is not settled.
        """
        return bool(self.questions) or self.needs_approval

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

    # Outcome first: on a done or in-flight task it is the one thing the reader
    # wants at a glance, above the plan that produced it.
    if doc.outcome:
        parts.append(f"## {H_OUTCOME}\n\n{doc.outcome.strip()}")

    if doc.understanding:
        parts.append(f"## {H_UNDERSTANDING}\n\n{doc.understanding.strip()}")

    if doc.plan:
        parts.append(f"## {H_PLAN}\n\n{_render_list(doc.plan, numbered=True)}")

    # Questions, then the approval row last — it is the decision the rest of
    # the section leads up to, and on a phone the thing you act on should be
    # the thing nearest your thumb.
    #
    # Note the interaction with the sentinel: a plan with no questions but
    # awaiting sign-off must NOT render `_No open questions._`, because both
    # parsers treat that as "this section asks nothing" and would return 0 open
    # and `answered = False` — a plan that can never be approved and never
    # reports why.
    if doc.questions or doc.needs_approval:
        lines = _render_list(doc.questions, numbered=True) if doc.questions else ""
        if doc.needs_approval:
            lines = f"{lines}\n{APPROVAL_ITEM}" if lines else APPROVAL_ITEM
        parts.append(f"## {H_QUESTIONS}\n\n{lines}")
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


def _canonical_heading(title: str) -> str:
    """Fold a Questions heading variant onto `H_QUESTIONS`.

    Their `isQuestionsHeading` tolerates `Questions:`, `Open questions`,
    `questions`. Ours required the exact string, which meant a human who
    retitled the heading made the section invisible to us while it stayed
    visible to them — and the board fires our wake on their reading of it.

    Folded here, in the one place that resolves a heading, rather than in the
    predicates: a second questions-section lookup would be the divergence
    again, one layer down.
    """
    if re.match(r"^(?:open\s+)?questions\b", title.strip(), re.IGNORECASE):
        return H_QUESTIONS
    return title


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
        title = _canonical_heading(m.group("title").strip())
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


def _strip_sentinel_markup(text: str) -> str:
    """Strip a list marker and surrounding emphasis, so `_No open questions._`
    is recognised however it was wrapped. Mirrors their `stripSentinelMarkup`."""
    s = text.strip()
    m = _BULLET_RE.match(s)
    if m:
        s = m.group("text").strip()
    m = re.match(r"^(\*{1,3}|_{1,3})([\s\S]*)\1$", s)
    if m:
        s = m.group(2).strip()
    return s


def _is_no_questions(body: str) -> bool:
    return bool(re.match(r"^no open questions\.?$",
                         _strip_sentinel_markup(body), re.IGNORECASE))


def _questions_body(body: str) -> tuple[list[str], Optional[str]]:
    """Split a Questions body into its items and the human's trailing reply.

    A transcription of their `parseQuestionsBody`, kept **deliberately separate
    from `_bullets`** even though both split the same text. They answer
    different questions, and folding one into the other was tried and reverted:

      - `_bullets` builds OUR document. It strips the list marker (the text is
        re-rendered next pass, so `1. ` surviving would come back as `1. 1. `),
        joins an INDENTED continuation to its bullet with a newline, and sends
        anything else to `human_text`.
      - this builds THEIR reading. Markers stay on, because `_task_item_state`
        needs the `- [` prefix to see a checkbox at all; a continuation joins
        with a space; and a reply is specifically prose that follows an item
        **after a blank line**, with a later item resetting it.

    That last rule is the one `questions_answered` rests on, and it is why
    `_bullets` cannot stand in: it calls any non-bullet line residue wherever it
    sits, so a paragraph typed *above* the questions would read as an answer.

    So this is a second parser of the same bytes, and that is the point — its
    job is to agree with a foreign implementation, not to model our document.
    Returns `(items, reply)`, `reply` None when nobody has replied.
    """
    items: list[str] = []
    reply: Optional[list[str]] = None
    blank_since_last_item = False

    for line in body.split("\n"):
        trimmed = line.strip()
        if not trimmed:
            if items:
                blank_since_last_item = True
            continue
        if _BULLET_RE.match(line):
            items.append(trimmed)
            blank_since_last_item = False
            reply = None
            continue
        if items and blank_since_last_item:
            if reply is None:
                reply = []
            reply.append(trimmed)
        elif items:
            items[-1] = f"{items[-1]} {trimmed}"
        else:
            items.append(trimmed)

    return [i for i in items if i], (" ".join(reply) if reply else None)


def _questions_section(text: str) -> str:
    """The `## Questions` body, with our own footer taken off first.

    Stripping the footer is not tidiness. `## Questions` is the last section of
    any plan that proposes no acceptance criteria, so `— pass 1` lands *inside*
    its body — and `_questions_body` reads a blank line followed by prose as
    the human's reply. Our own bookkeeping would then answer our own question:
    `open_question_count` drops to 0 and `questions_answered` goes true the
    instant we render, before anyone has read it.

    `parse` has stripped the footer first since it was written, for this exact
    reason. The predicates have to do it too.
    """
    sections, _ = _sections(_FOOTER_RE.sub("", text or ""))
    return sections.get(H_QUESTIONS, "")


def open_question_count(text: str) -> int:
    """How many things this task is waiting on a human for.

    Mirrors their `openQuestionCount`, which is what the card badge shows.

    An **unticked** task-list box is an open ask on its own terms: a reply does
    not tick a box, so it keeps counting after the prose has gone quiet, and it
    is exempt from both the `?` rule and the reply rule. A **ticked** box never
    counts — its own state is the answer. A Questions section with no task-list
    items counts exactly as it always did.
    """
    body = _questions_section(text)
    if not body or _is_no_questions(body):
        return 0

    items, reply = _questions_body(body)
    unticked = sum(1 for i in items if _task_item_state(i) is False)
    prose = [i for i in items if _task_item_state(i) is None]

    if reply is not None:
        open_prose = 0
    else:
        asked = [i for i in prose if "?" in i]
        open_prose = len(asked) if asked else len(prose)

    return unticked + open_prose


def questions_answered(text: str) -> bool:
    """True once the human has done their part.

    Mirrors their `questionsAnswered` — and this one matters more than the
    count, because **the board fires our wake on their copy of it**
    (`notifyNotesWrite`). Both halves must hold:

      - every task-list item is ticked (an unticked box is an ask no amount of
        prose answers — ticking it is the answer);
      - the prose questions, if any, have a reply trailing them.

    With no task-list items this is byte-for-byte the rule that predates them.
    So a ticked `- [ ] Approve this plan` and a typed reply are the same event
    to both repos, which is exactly why approval needed no second channel.
    """
    body = _questions_section(text)
    if not body or _is_no_questions(body):
        return False

    items, reply = _questions_body(body)
    if not items:
        return False

    boxes = [s for s in (_task_item_state(i) for i in items) if s is not None]
    if any(not ticked for ticked in boxes):
        return False

    prose = [i for i in items if _task_item_state(i) is None]
    if prose:
        return reply is not None
    return bool(boxes)


@dataclass(frozen=True)
class ChecklistItem:
    """One `- [ ] …` row, addressed by its position in the document."""

    #: Zero-based position among ALL task-list items, in document order. The
    #: item's identity for a toggle: the text isn't unique (two `Approve this
    #: plan` rows are legal) and a line number shifts when anything above it
    #: is edited.
    ordinal: int
    checked: bool
    text: str


def checklist_items(notes: Optional[str]) -> list[ChecklistItem]:
    """Every task-list item in `notes`, in document order.

    Fence-aware: a `- [ ]` inside a fenced example is text, not a control.

    We deliberately do NOT port their `toggleChecklistItem`. Ticking a box is
    a human act performed in their UI; a copy here would be a write path
    nothing calls, and the one thing worse than two implementations of a
    format is a second one nobody exercises.
    """
    if not notes:
        return []
    out: list[ChecklistItem] = []
    in_fence = False
    for line in notes.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _TASK_ITEM_RE.match(line)
        if m:
            out.append(ChecklistItem(ordinal=len(out),
                                     checked=m.group("box") != " ",
                                     text=m.group("text").strip()))
    return out


def pending_approval(notes: Optional[str]) -> Optional[ChecklistItem]:
    """The first UNTICKED approval row, or None when there is nothing to sign.

    `None` is the signal the pipeline acts on: no unticked approval row means
    either the human ticked it — go — or the plan never asked for one.
    Scanned across the whole document rather than only `## Questions`, matching
    their `pendingApproval`, so nothing about approval depends on the heading
    being spelled right.
    """
    for item in checklist_items(notes):
        if not item.checked and _APPROVAL_RE.match(item.text):
            return item
    return None


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

    doc.outcome = sections.get(H_OUTCOME, "").strip()
    doc.understanding = sections.get(H_UNDERSTANDING, "").strip()
    doc.plan = section(H_PLAN)
    doc.acceptance = section(H_ACCEPTANCE)
    doc.blast_radius = section(H_BLAST)

    questions_body = sections.get(H_QUESTIONS, "")
    if _is_no_questions(questions_body.strip().split("\n", 1)[0]):
        doc.questions = []
        # A human who answered by typing under "_No open questions._" still
        # said something; keep it.
        extra = questions_body.strip().split("\n", 1)
        if len(extra) > 1 and extra[1].strip():
            residues.append(extra[1].strip())
    else:
        # A task-list row is not a prose question, and must not survive into
        # `doc.questions` — the next pass re-renders that list, so a `- [ ]`
        # round-tripping through it would come back as `1. [ ] Approve…`,
        # numbered, and duplicated alongside the one `needs_approval` emits.
        # The flag below is how an approval row survives a pass instead.
        doc.questions = [q for q in section(H_QUESTIONS)
                         if not _CHECKBOX_TEXT_RE.match(q)]

    # Approval is a property of the whole document, not of the Questions
    # section, matching their `pendingApproval` — a plan that puts the row
    # elsewhere is still awaiting sign-off.
    doc.needs_approval = pending_approval(text) is not None

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


def with_trailing_note(rendered: str, block: str) -> str:
    """Put `block` after the last section but before the `— pass N` footer.

    For things that happened *to* a document rather than being part of it — a
    landing gate refusing the diff, a PR being rejected upstream. Those must
    not become the headline: the plan is what the reader came for, and burying
    it under a failure notice is what made a refusal read as though the plan
    itself were the problem.

    It lives here because the footer's position is this module's business, not
    the caller's. `reconcile` appends *after* the footer for the same class of
    thing; before it is better — the footer reads as the document's end mark,
    so anything past it looks like someone else's text pasted on.
    """
    block = (block or "").strip()
    if not block:
        return rendered
    m = None
    for m in _FOOTER_RE.finditer(rendered):
        pass  # the LAST footer: a human may have pasted an older one above
    if m is None:
        return rendered.rstrip() + "\n\n" + block + "\n"
    return (rendered[:m.start()].rstrip() + "\n\n" + block + "\n\n"
            + rendered[m.start():].lstrip())


def has_known_section(text: str) -> bool:
    """True if `text` contains at least one heading this module emits.

    The question `parse` cannot answer. `parse` never raises — right for
    `notes`, which a human may have mangled — so a reply that is not one of
    our documents at all comes back as an empty `PlanDoc`, indistinguishable
    from a well-formed document that happens to propose nothing. Those two
    mean opposite things when the reply came from the *agent*: one is "I
    looked and there is nothing to do", the other is "this is not a plan".

    Use it on agent output, not on `notes`. A human's raw capture legitimately
    has no headings — that is `looks_unplanned`.
    """
    sections, _ = _sections(text or "")
    return bool(sections)


def looks_unplanned(text: str) -> bool:
    """True when `notes` has never held one of our documents.

    Raw capture — the human's own words, or nothing at all. Distinguishing
    this from a plan awaiting answers is what stops the runner treating a
    first-time task as a stalled conversation.
    """
    doc = parse(text)
    return not (doc.understanding or doc.plan or doc.questions or doc.settled)
