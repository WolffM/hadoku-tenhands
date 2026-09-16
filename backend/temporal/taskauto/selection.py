"""What the runner should pick up next, and from which repo.

Pure policy over a `BoardSnapshot` — no I/O, no clock of its own, no board
writes. The runner reads a board, asks this what to do, and does it. Keeping
it pure is what makes the interesting decisions testable, because every one
of them is a judgement call rather than a mechanism.

hadoku-task deliberately holds none of this ("there is no /agent/eligible" —
deciding what's ready means knowing which state feeds which job, which is
pipeline knowledge). This module is that knowledge.

── What autoland v3 changed ──────────────────────────────────────────────

**The lane is the repo now, not the state.** v2 read a task's lane to know
what to do with it, and the lane-priority table that did so is gone. It could
not survive the axis turning: a task sitting in `hadoku-conjure` tells you
where the work is, and nothing at all about whether it is planned, approved,
running or stuck.

So state comes from two places instead, and the split is deliberate:

- **`task.status.kind`** — the phase WE last published. Four values, and they
  are the state machine: `working` (ours), `waiting` (yours), `blocked`
  (stuck, yours), `done`. Absent means untouched.
- **the notes** — what the human DID about a `waiting` task. Only the human
  writes them between our turns, so they are the only evidence of a reply.

Reading the phase off a field we wrote, rather than re-deriving it from the
document each sweep, is what keeps "the pipeline is mid-implementation" and
"the plan happens to have no open questions" from looking identical — which
they do in the notes alone, and which v2 only got away with because the lane
said so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.task_board import BoardSnapshot, BoardTask, TaskStatus

from . import plan_notes

# ── The phases, as `status.kind` spells them ──────────────────────────────
# Mirrors TASK_STATUS_KINDS in services.task_board, which mirrors hadoku-task.

STATUS_WORKING = "working"
STATUS_WAITING = "waiting"
STATUS_BLOCKED = "blocked"
STATUS_DONE = "done"

#: How long a task must sit untouched before we plan or route it.
#:
#: The Inbox is where half-formed thoughts land; acting on one the instant it
#: appears means planning against a sentence still being typed.
#:
#: One minute, not five. Five was chosen when the ONLY thing that could pick an
#: Inbox task up was the backstop sweep, so the settle window was free — it hid
#: inside a median 45-minute wait and cost nothing observable. Now that a
#: capture wakes a run in ~18s (`taskauto.yml`, the `repository_dispatch`
#: trigger), this window IS the latency, so it has to be the smallest value
#: that still does its job.
#:
#: The dispatch path sleeps for this long before sweeping — keep the two in
#: step. `taskauto.yml`'s "Let a fresh capture settle" step is the other half.
DEFAULT_SETTLE = timedelta(minutes=1)


# ── Jobs ──────────────────────────────────────────────────────────────────

#: Decide which repo an Inbox task belongs to and move it there. **Touches no
#: checkout**, which is the whole reason it is a job of its own rather than a
#: first step inside `plan` — see `runner.turn` on lock ordering.
JOB_ROUTE = "route"
JOB_PLAN = "plan"
JOB_IMPLEMENT = "implement"


# ── Building a chip ───────────────────────────────────────────────────────
# Four one-line factories rather than `TaskStatus(kind=...)` at forty call
# sites: the kind is the state machine, so the set of things that can publish
# one should be enumerable by grepping this module.


def working(label: str) -> TaskStatus:
    """We own this task right now."""
    return TaskStatus(kind=STATUS_WORKING, label=label)


def waiting(label: str, href: str = "") -> TaskStatus:
    """It is the human's move — a plan to sign, or a PR to merge."""
    return TaskStatus(kind=STATUS_WAITING, label=label, href=href)


def blocked(label: str) -> TaskStatus:
    """Stuck in a way the pipeline cannot resolve on its own."""
    return TaskStatus(kind=STATUS_BLOCKED, label=label)


def done(label: str, href: str = "") -> TaskStatus:
    """Finished. Usually released with `complete=True`, which archives it."""
    return TaskStatus(kind=STATUS_DONE, label=label, href=href)


@dataclass(frozen=True)
class Pickup:
    """A decision to claim one task and run one job."""

    task: BoardTask
    job: str
    #: The repo lane the task is in and stays in. Empty for `route`, which is
    #: the job that works out what it should be.
    lane: str
    #: `owner/name`, resolved from the lane. Empty for `route`.
    repo: str
    #: Why this one — carried into logs and the claim outcome so a board that
    #: did something surprising can be explained after the fact.
    reason: str
    #: True when resuming a crashed run rather than starting fresh.
    is_recovery: bool = False


@dataclass(frozen=True)
class Idle:
    """Nothing to do, and the reason — which is the useful part.

    "Idle" and "blocked behind an in-flight task" look identical from outside
    and mean very different things when a repo looks stuck.
    """

    reason: str


Decision = object  # Pickup | Idle


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _settled(task: BoardTask, now: datetime, settle: timedelta) -> bool:
    touched = _parse_iso(task.last_touched)
    if touched is None:
        # No usable timestamp. Treat as settled rather than stranding the task
        # forever — the cost of planning slightly early is a question on
        # someone's phone; the cost of never planning is silence.
        return True
    return now - touched >= settle


def _kind(task: BoardTask) -> str:
    return task.status.kind if task.status else ""


def _oldest(tasks: list[BoardTask]) -> BoardTask:
    return min(tasks, key=lambda t: t.last_touched or "")


# ── What a human did to a task we parked ──────────────────────────────────


def human_verdict(task: BoardTask) -> Optional[str]:
    """What the human's notes say to do next with a `waiting` task.

    Returns a job, or None when they have not answered yet.

    Three outcomes, and the middle one is the one worth being careful about:

    - **approval ticked** → `implement`. The sign-off, and the only thing that
      authorises writing code. A ticked box is unambiguous in a way that
      interpreting prose never is, which is exactly why approval is a box.
    - **replied, approval still open** → `plan`. This is "send it back": they
      answered the questions but did not sign off, so the answer feeds another
      planning pass rather than an implementation. `questions_answered` is
      false here — it requires every box ticked — so this cannot be read off
      that predicate alone, and reading it off that alone would silently
      implement a plan nobody approved.
    - **neither** → None. Still waiting.

    A plan that never asked for approval (`needs_approval` false, no open
    questions) is not waiting on anyone; `choose` never parks one as `waiting`,
    so it does not reach here.
    """
    notes = task.notes or ""
    if plan_notes.pending_approval(notes) is None and _was_asked(notes):
        return JOB_IMPLEMENT
    doc = plan_notes.parse(notes)
    if doc.human_text.strip():
        return JOB_PLAN
    return None


def _was_asked(notes: str) -> bool:
    """Did this document ever carry an approval row?

    `pending_approval` answers "is one outstanding", and absent-because-ticked
    has to be told apart from absent-because-never-asked — otherwise every
    plan that asks nothing reads as approved. The ticked row is still in the
    document, so its presence is the evidence.
    """
    return any(i.checked and i.text.lower().startswith("approve")
               for i in plan_notes.checklist_items(notes))


# ── The decision ──────────────────────────────────────────────────────────


def choose(board: BoardSnapshot, lane_tag: str, *, now: datetime,
           settle: timedelta = DEFAULT_SETTLE) -> Decision:
    """Pick the next task to claim in ONE repo lane, or explain why not.

    Priority, highest first:

    1. **Recovery** — a task we published as `working` that no longer holds a
       claim. The run crashed; nobody else will pick it up. It outranks
       everything because the work is already part-done and its evidence is on
       disk.
    2. **A human answered** — cheapest path to unblocking a conversation they
       are waiting on, and the only one where someone is actually waiting.
    3. **Unplanned work** — a task in this repo that has never been planned.
       Oldest first, once settled.

    `blocked` and `done` are terminal for us: a human has to act, and claiming
    from them would take the decision away from them. A `waiting` task with no
    verdict is likewise left alone — including one holding an open PR, which is
    `reconcile`'s business rather than selection's.
    """
    repo = board.repo_for(lane_tag)
    if not repo:
        return Idle(f"{lane_tag} is not a repo lane")

    tasks = board.tasks_in(lane_tag)

    # One task in flight per REPO, not per board — the v2 rule scaled down to
    # the axis it was always really about. Several tasks in one repo routinely
    # touch the same files, so concurrent diffs collide; two repos never do.
    # This is the change that makes one board with N repos strictly better
    # than N boards: the serialisation is per-repo either way, but the read,
    # the change feed and the human's attention are shared.
    #
    # Checked against the server's per-task `claimed` flag rather than our own
    # `status`, because a task can read `working` with an expired claim — which
    # is precisely the recovery case below, not in-flight work.
    in_flight = [t for t in tasks if t.claimed]
    if in_flight:
        return Idle(f"{in_flight[0].id} is in flight in {repo}")

    crashed = [t for t in tasks if _kind(t) == STATUS_WORKING]
    if crashed:
        task = _oldest(crashed)
        # Resume as whatever it was doing. A crashed implementation re-runs as
        # an implementation: the approval is still ticked in the notes, and
        # re-planning an approved task would throw away a decision the human
        # already made.
        job = (JOB_IMPLEMENT if plan_notes.pending_approval(task.notes) is None
               and _was_asked(task.notes) else JOB_PLAN)
        return Pickup(task=task, job=job, lane=lane_tag, repo=repo,
                      reason="resuming a crashed run", is_recovery=True)

    for task in sorted((t for t in tasks if _kind(t) == STATUS_WAITING),
                       key=lambda t: t.last_touched or ""):
        verdict = human_verdict(task)
        if verdict == JOB_IMPLEMENT:
            return Pickup(task=task, job=verdict, lane=lane_tag, repo=repo,
                          reason="approved by human")
        if verdict == JOB_PLAN:
            return Pickup(task=task, job=verdict, lane=lane_tag, repo=repo,
                          reason="human answered, re-planning")

    unplanned = [t for t in tasks
                 if _kind(t) in ("", STATUS_WORKING)
                 and plan_notes.looks_unplanned(t.notes)]
    ready = [t for t in unplanned if _settled(t, now, settle)]
    if unplanned and not ready:
        return Idle(f"{len(unplanned)} task(s) in {repo} still settling "
                    f"(< {int(settle.total_seconds())}s since last edit)")
    if ready:
        return Pickup(task=_oldest(ready), job=JOB_PLAN, lane=lane_tag,
                      repo=repo, reason="filed here, not yet planned")

    return Idle(f"nothing waiting in {repo}")


def choose_unrouted(board: BoardSnapshot, *, now: datetime,
                    settle: timedelta = DEFAULT_SETTLE) -> Decision:
    """Pick an Inbox task to route to a repo lane.

    The Inbox is board-wide and belongs to no repo, which is the whole problem
    it poses: under one board per repo a fresh capture already knew where it
    was going, and now it does not. Routing is the job that decides.

    Deliberately separate from `choose` and deliberately checkout-free. See
    `runner.turn` for why that matters — it is the only way to keep taking the
    checkout lock before the claim, which is the ordering that makes losing a
    race cost nothing.
    """
    if not board.repo_lanes:
        return Idle("board has no repo lanes — not a v3 automation board")

    inbox = board.untagged()
    if not inbox:
        return Idle("inbox is empty")

    # An Inbox task can be claimed by a router that then died. It carries no
    # lane, so `choose` will never see it; recovery has to happen here.
    unclaimed = [t for t in inbox if not t.claimed]
    if not unclaimed:
        return Idle(f"{len(inbox)} inbox task(s), all in flight")

    ready = [t for t in unclaimed if _settled(t, now, settle)]
    if not ready:
        return Idle(f"{len(unclaimed)} inbox task(s) still settling "
                    f"(< {int(settle.total_seconds())}s since last edit)")

    return Pickup(task=_oldest(ready), job=JOB_ROUTE, lane="", repo="",
                  reason="new capture, settled")


def malformed_note(board: BoardSnapshot) -> str:
    """A line about tasks no branch above can see, or empty.

    A task carrying two lane tags resolves to no lane, isn't untagged either,
    and so is invisible to both `choose` and `choose_unrouted`. It would sit
    there indefinitely while every repo reported "nothing waiting", which is
    the least useful true statement available. A write would fail
    LANE_INVALID anyway — a human has to repair it — so say so.

    Rarer under v3 than v2, because the agent path no longer writes lanes at
    all, but not impossible: the board stores tags as one string and an
    activation that renames a repo lane can leave a task carrying both.
    """
    malformed = board.malformed()
    if not malformed:
        return ""
    ids = ", ".join(t.id for t in malformed[:3])
    return (f"{len(malformed)} task(s) carry an unusable lane tag and need "
            f"repair ({ids})")
