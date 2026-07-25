"""Reading the human's own text: `bug-` classification and `allow-protected`.

Two small parsers that carry more weight than their size suggests.

**`bug-`** is the user's existing convention, not one we invented, and it
decides how a task gets verified: a breakage claim has to go red before it
can go green, while a change request has nothing to reproduce and is
verified against a stated end condition instead. Demanding a reproduction
from `make coffee theme default` is a category error that would stall it
forever.

**`allow-protected`** is an authorisation, and authorisations must come from
the human. See `extract_allow_protected` for the trap this module exists to
avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BUG_PREFIX_RE = re.compile(r"^\s*bug\s*[-:]\s*", re.IGNORECASE)

# `allow-protected: <glob>[, <glob>...]`.
#
# Two patterns on purpose, because the two sources carry different risk.
#
# In NOTES the directive must start a line. Notes run to kilobytes and may
# legitimately discuss the deny-list ("we could add allow-protected: X if
# needed"); letting prose grant an authorisation would be absurd.
#
# In a TITLE it may appear anywhere. A title is one short line, entirely
# human-written, with no room for incidental discussion — and "fix deploy
# allow-protected: .github/workflows/deploy.yml" is how someone actually
# types this on a phone. Requiring line-start there would silently ignore
# the human's authorisation, which fails in the more annoying direction:
# the task stalls and they can't see why.
ALLOW_PROTECTED_LINE_RE = re.compile(
    r"^\s*allow-protected\s*:\s*(?P<globs>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
ALLOW_PROTECTED_INLINE_RE = re.compile(
    r"allow-protected\s*:\s*(?P<globs>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class ItemKind:
    """How a task should be verified."""

    is_bug: bool

    @property
    def needs_repro(self) -> bool:
        """Bugs must be demonstrated broken before they can be shown fixed.

        Change requests must not be held to this. Nothing is claimed to be
        broken, so there is no red state to reach — they're verified against
        a declared acceptance check instead (gates G2/G8).
        """
        return self.is_bug


def classify(title: str) -> ItemKind:
    """Classify from the task title alone.

    Deliberately only the title. The body may quote an error message or
    discuss a bug in passing without the task itself being a bug report, and
    a classifier that reads the whole text would flip on that.
    """
    return ItemKind(is_bug=bool(BUG_PREFIX_RE.match(title or "")))


def strip_bug_prefix(title: str) -> str:
    """The task title without its `bug-` marker, for prompts and PR bodies."""
    return BUG_PREFIX_RE.sub("", title or "").strip()


def extract_allow_protected(
    *, title: str = "", notes_at_claim: str = ""
) -> list[str]:
    """Path globs the human authorised the agent to touch.

    G6 refuses to auto-merge changes to CI, secrets, migrations, infra, or
    the pipeline's own code. `allow-protected:` is the per-task override —
    the human naming a specific blast radius they accept.

    **The sources are deliberately restricted, and this is the whole point
    of the function.** The planning agent rewrites `notes` on every pass. If
    this read live notes, the agent could write its own authorisation to
    edit CI or its own gates, and the deny-list would enforce nothing. An
    agent that can grant itself permission is not authorised, it is
    unsupervised.

    So we read only:

      - `title` — which the agent never rewrites (directive may appear
        anywhere in it; see the pattern note above), and
      - `notes_at_claim` — the snapshot taken when the claim was acquired,
        which is the human's version by construction, since we cannot have
        written to it before holding the claim.

    Passing live notes here would reintroduce exactly the hole this exists
    to close. The general rule: no gate may read its own authorisation from
    a field the agent can write.
    """
    globs: list[str] = []
    for source, pattern in (
        (title or "", ALLOW_PROTECTED_INLINE_RE),
        (notes_at_claim or "", ALLOW_PROTECTED_LINE_RE),
    ):
        for m in pattern.finditer(source):
            for raw in m.group("globs").split(","):
                candidate = raw.strip().strip("`'\"")
                if candidate and candidate not in globs:
                    globs.append(candidate)
    return globs
