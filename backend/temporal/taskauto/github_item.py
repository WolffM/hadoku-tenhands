"""Re-hydrating a task that was seeded from a GitHub issue or PR.

The board's "automate open items" button seeds one `Address #N` task per open
issue/PR and puts a **280-character** preview of the item's body into the task
notes (`_BODY_SNIPPET_MAX` in `routes/taskauto_routes.py`). That cap is right
for a board card and ruinous for planning, which reads the same notes as its
only account of what the human wants.

Issue #19 on hadoku-aggregator is 3,783 characters, so the planner saw 7% of
it. Everything past `- [ ] Quick hygiene: README prese…` was gone — including
the entire section naming the four deliverables and the *other repo* they land
in. It planned against the fragment and, having no way to know a fragment was
what it had, asked a human to paste back data this process had already fetched
and thrown away.

The planner cannot recover the rest itself, and must not be able to: it runs
with `--allowed-tools Read,Grep,Glob,Bash(git log:*),Bash(git show:*)` and a
scrubbed environment holding no `GH_TOKEN` (`agent.py`, containments 1 and 2).
Both are deliberate and neither should change. So the fetch belongs *here*, on
the trusted side of that boundary — the same side `Lander` already runs `gh`
from — and its result is handed to the agent as prompt text it did not have to
reach for.

Three things this module refuses to do quietly, each because the quiet version
is what caused the failure it exists to prevent:

- **A failed fetch is announced, not omitted.** No block and a block reading
  "there is nothing more" are indistinguishable to the agent, and the second is
  a lie that buys a confidently wrong plan. `_unavailable()` renders the
  failure into the prompt so the agent knows to ask instead of infer.
- **Truncation is labelled in characters.** A bare `…` is precisely what made
  the original loss invisible. If a body genuinely exceeds `MAX_ITEM_CHARS` the
  cut says how much it dropped.
- **Absent status is stated as absent.** "checks: none reported" is a fact the
  agent must be told, because the alternative — saying nothing about checks —
  is what let it invent a failing-CI backlog for a PR that has never had a
  check run against it.
"""

from __future__ import annotations

import json as _json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

#: Titles the "automate open items" button generates: `Address #19`,
#: `Address PR #21`. Anchored at the start and on the button's own word, so an
#: ordinary human title that merely mentions `#3` in passing is never mistaken
#: for a seeded one — hydrating the *wrong* issue is worse than not hydrating,
#: since a plausible irrelevant issue body is harder to notice than a missing
#: one. Trailing text is tolerated because people rename these by hand.
SEEDED_TITLE_RE = re.compile(
    r"^\s*address\s+(?:(?P<pr>pr|pull\s+request)\s+)?#(?P<number>\d+)\b",
    re.IGNORECASE)

#: Ceiling on one rendered body. No real issue approaches it; it exists so a
#: pathological body cannot crowd out the rest of the prompt. Exceeding it is
#: reported in the text — see the module docstring.
MAX_ITEM_CHARS = 16000

#: Per-comment ceiling. Comment threads are where people paste stack traces.
MAX_COMMENT_CHARS = 1200

GH_TIMEOUT_S = 25

ISSUE_FIELDS = "number,title,url,state,author,body,labels,comments"
PR_FIELDS = ("number,title,url,state,isDraft,author,body,headRefName,"
             "baseRefName,reviewDecision,statusCheckRollup,comments,reviews")


class ItemUnavailable(RuntimeError):
    """`gh` could not tell us about the item. Never swallowed into silence."""


@dataclass(frozen=True)
class ItemRef:
    #: "issue" or "pr".
    kind: str
    number: int

    @property
    def label(self) -> str:
        return f"{'PR' if self.kind == 'pr' else 'issue'} #{self.number}"


def parse_seeded_ref(title: str) -> Optional[ItemRef]:
    """The issue/PR a task title was seeded from, or None if it wasn't.

    None is the safe answer and the common one: a hand-typed task has no item
    behind it, and planning proceeds exactly as it did before.
    """
    m = SEEDED_TITLE_RE.match(title or "")
    if not m:
        return None
    return ItemRef("pr" if m.group("pr") else "issue", int(m.group("number")))


def _default_run(argv: Sequence[str]) -> tuple[bool, str]:
    """Run `gh` with the *parent's* environment — the trusted side.

    Deliberately not `agent.scrubbed_env()`. That allow-list exists to keep
    credentials away from the untrusted agent; this call is the tenhands
    process reading a public API on its own behalf, which is the same thing
    `Lander` does when it opens the PR.
    """
    try:
        p = subprocess.run(list(argv), capture_output=True, text=True,
                           check=False, timeout=GH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {GH_TIMEOUT_S}s"
    except FileNotFoundError:
        return False, "gh not found on PATH"
    return p.returncode == 0, (p.stdout if p.returncode == 0 else p.stderr)


def _gh_json(run: Callable[..., tuple[bool, str]], argv: Sequence[str]):
    ok, out = run(["gh", *argv])
    if not ok:
        raise ItemUnavailable(
            f"`gh {' '.join(argv[:3])}` failed: {(out or '').strip()[:200]}")
    try:
        return _json.loads(out or "null")
    except ValueError:
        raise ItemUnavailable(
            f"`gh {' '.join(argv[:3])}` returned unparseable JSON") from None


# ── rendering ─────────────────────────────────────────────────────────────

def _login(who: Optional[dict]) -> str:
    who = who or {}
    return who.get("login") or who.get("name") or "unknown"


def _capped(text: str, limit: int) -> str:
    text = (text or "").strip()
    if not text:
        return "_(empty)_"
    if len(text) <= limit:
        return text
    return (f"{text[:limit]}\n[cut here — {len(text) - limit} more characters "
            f"not shown]")


def _comments_block(comments: Optional[list], heading: str) -> str:
    comments = comments or []
    if not comments:
        return f"{heading}: none"
    lines = [f"{heading} ({len(comments)}):"]
    for c in comments:
        who = _login(c.get("author") or c.get("user"))
        lines.append(f"  [{who}] {_capped(c.get('body'), MAX_COMMENT_CHARS)}")
    return "\n".join(lines)


def _review_comments_block(items: Optional[list]) -> str:
    """Inline review comments — the ones anchored to a file and line.

    `gh pr view --json comments` does NOT include these; it returns only the
    conversation tab. They are fetched separately because they are exactly the
    "review feedback" a task titled `Address PR #N` is most likely to be about.
    """
    items = items or []
    if not items:
        return "inline review comments: none"
    lines = [f"inline review comments ({len(items)}):"]
    for c in items:
        where = c.get("path") or "?"
        line_no = c.get("line") or c.get("original_line")
        anchor = f"{where}:{line_no}" if line_no else where
        who = _login(c.get("user"))
        lines.append(f"  [{who}] {anchor} — "
                     f"{_capped(c.get('body'), MAX_COMMENT_CHARS)}")
    return "\n".join(lines)


def _checks_block(rollup: Optional[list]) -> str:
    """One line per check, or an explicit statement that there are none.

    Handles both rollup shapes GitHub returns: `CheckRun` (Actions and other
    apps — `name`/`conclusion`) and `StatusContext` (the older commit-status
    API — `context`/`state`).
    """
    rollup = rollup or []
    if not rollup:
        return ("checks: NONE REPORTED on this branch — no CI has ever run "
                "against it. There is no failing check to fix.")
    lines = [f"checks ({len(rollup)}):"]
    for c in rollup:
        name = c.get("name") or c.get("context") or "?"
        verdict = c.get("conclusion") or c.get("state") or c.get("status") or "?"
        lines.append(f"  {name}: {verdict}")
    return "\n".join(lines)


def _reviews_block(reviews: Optional[list], decision: str) -> str:
    reviews = reviews or []
    decision = (decision or "").strip()
    if not reviews:
        head = ("reviews: none — nobody has reviewed this PR"
                if not decision else f"reviews: none recorded (decision: {decision})")
        return head
    lines = [f"reviews ({len(reviews)}"
             f"{', decision: ' + decision if decision else ''}):"]
    for r in reviews:
        lines.append(f"  [{_login(r.get('author'))}] {r.get('state') or '?'} "
                     f"{_capped(r.get('body'), MAX_COMMENT_CHARS)}")
    return "\n".join(lines)


def _render_issue(repo: str, d: dict) -> str:
    labels = ", ".join(
        lb.get("name", "") for lb in (d.get("labels") or [])) or "none"
    return "\n".join([
        f"--- issue #{d.get('number')}: {d.get('title') or ''} ---",
        f"repo:   {repo}",
        f"url:    {d.get('url') or ''}",
        f"state:  {d.get('state') or '?'}, opened by {_login(d.get('author'))}",
        f"labels: {labels}",
        "",
        "body (in full):",
        _capped(d.get("body"), MAX_ITEM_CHARS),
        "",
        _comments_block(d.get("comments"), "comments"),
    ])


def _render_pr(repo: str, d: dict, review_comments: Optional[list]) -> str:
    draft = "DRAFT" if d.get("isDraft") else "not a draft"
    return "\n".join([
        f"--- PR #{d.get('number')}: {d.get('title') or ''} ---",
        f"repo:   {repo}",
        f"url:    {d.get('url') or ''}",
        f"state:  {d.get('state') or '?'} ({draft}), "
        f"opened by {_login(d.get('author'))}",
        f"branch: {d.get('headRefName') or '?'} → {d.get('baseRefName') or '?'}",
        "",
        "body (in full):",
        _capped(d.get("body"), MAX_ITEM_CHARS),
        "",
        _checks_block(d.get("statusCheckRollup")),
        _reviews_block(d.get("reviews"), d.get("reviewDecision") or ""),
        _review_comments_block(review_comments),
        _comments_block(d.get("comments"), "conversation comments"),
    ])


#: Why the task exists at all. The button seeds one task per OPEN item and
#: nothing else, so a bare `Address PR #21` carries no statement of intent —
#: and an agent handed a bare imperative will supply one. It invented an
#: outstanding review backlog for a PR with zero comments and zero checks, then
#: wrote plan steps and an acceptance criterion against the backlog it had
#: imagined. Saying plainly that no intent was stated is what stops that.
_PROVENANCE = """\
Why this task exists: it was seeded from the open item above, and being open is
the ONLY reason it exists. Nobody has stated what they want done with it beyond
"address it". The status lines above are complete — if they say a PR has no
reviews and no checks, then there is no review feedback and no failing CI to
resolve, and you must not plan as though there were. Plan against what the item
itself asks for."""


def _unavailable(repo: str, ref: ItemRef, reason: str) -> str:
    """What the agent is told when the fetch failed.

    Announced rather than omitted: silence here reads to the agent as "the
    truncated notes are the whole story", which is the failure this module was
    written to end.
    """
    return "\n".join([
        f"THE GITHUB ITEM THIS TASK WAS SEEDED FROM ({repo} {ref.label}) COULD "
        f"NOT BE FETCHED:",
        f"  {reason}",
        "",
        "So anything about this item in the task notes below is a 280-character "
        "PREVIEW, not the item. Do not assume you have read it — the parts you "
        "cannot see are the parts most likely to matter. If you cannot plan "
        "without them, say so and ask.",
    ])


def render(repo: str, ref: ItemRef, *,
           run: Callable[..., tuple[bool, str]] = _default_run) -> str:
    """Fetch one issue/PR and render it as a prompt block. Raises on failure."""
    if ref.kind == "pr":
        d = _gh_json(run, ["pr", "view", str(ref.number), "--repo", repo,
                           "--json", PR_FIELDS])
        if not isinstance(d, dict):
            raise ItemUnavailable(f"`gh pr view` returned no object for {ref.label}")
        # A best-effort extra: the inline comments are the most valuable part
        # for a PR task, but failing to get them must not cost us the body we
        # already have. Their absence is reported as "none", which is honest
        # only because the primary fetch above succeeded.
        try:
            review_comments = _gh_json(
                run, ["api", f"repos/{repo}/pulls/{ref.number}/comments",
                      "--paginate"])
        except ItemUnavailable as e:
            logger.warning("inline review comments unavailable for %s %s: %s",
                           repo, ref.label, e)
            review_comments = []
        body = _render_pr(repo, d, review_comments if isinstance(review_comments, list) else [])
    else:
        d = _gh_json(run, ["issue", "view", str(ref.number), "--repo", repo,
                           "--json", ISSUE_FIELDS])
        if not isinstance(d, dict):
            raise ItemUnavailable(f"`gh issue view` returned no object for {ref.label}")
        body = _render_issue(repo, d)

    return "\n".join([
        "THE GITHUB ITEM THIS TASK WAS SEEDED FROM, fetched just now IN FULL "
        "(the task notes below carry only a 280-character preview of it — "
        "prefer this):",
        body,
        "--- end of item ---",
        "",
        _PROVENANCE,
    ])


def hydrate(repo: str, title: str, *,
            run: Callable[..., tuple[bool, str]] = _default_run) -> str:
    """The prompt block for a task's GitHub item, or "" if it has none.

    Never raises. Planning is not worth failing over a `gh` hiccup — but the
    hiccup is *reported into the prompt* rather than dropped, so the agent
    never mistakes a fetch failure for an absence of context.
    """
    ref = parse_seeded_ref(title)
    if ref is None:
        return ""
    try:
        return render(repo, ref, run=run)
    except ItemUnavailable as e:
        logger.warning("could not hydrate %s %s: %s", repo, ref.label, e)
        return _unavailable(repo, ref, str(e))
    except Exception as e:  # noqa: BLE001 - see docstring: never raises
        logger.exception("unexpected failure hydrating %s %s", repo, ref.label)
        return _unavailable(repo, ref, f"unexpected {type(e).__name__}: {e}")
