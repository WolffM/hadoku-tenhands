"""What actually happened to the pull request, written back to the board.

`pr` mode ends by opening a pull request and moving the task to `landed`,
which `autoland` v2 defines as *"the PR is open, gates green, and waiting on
you. Review it and merge."* That is a promise about the present tense, and
nothing was keeping it. The pipeline never looked at a PR again, so `landed`
was a write-once state and every task in it went on claiming to be waiting for
a merge no matter what the human actually did.

Measured on 2026-08-04, before this module existed: **13 of 14** tasks holding
a PR link disagreed with their PR. Ten were merged days earlier and still read
"NOT merged — this is waiting on you". Three had been **closed without
merging** — a human saying *no* — and still read as work waiting to be
accepted. The dashboard did not cover for it either: `_prs_for()` lists
`--state open`, so a rejected PR vanishes from the status page at the same
moment the board starts lying about it. Nothing anywhere said "this was
rejected", and nothing would ever plan it again.

`watch.py` calls watching-what-you-did the load-bearing safety property of the
whole pipeline, and it is — but it only covers `push` mode. This is the same
property for `pr` mode, where the deciding signal is not a health check but a
person clicking merge or close.

**Three outcomes, and only two of them are ours to act on.**

- **Merged** — done. Complete the task, which archives it. `release()` has
  always documented `complete: true` as "how `landed` avoids growing without
  bound"; it simply had no caller.
- **Closed, unmerged** — rejected. Back to `replan`, with the rejection
  appended as residue so `plan_notes.parse` hands it to the planning agent as
  `human_text`. That is the same channel a human's typed reply arrives on,
  which is right: a closed PR *is* the reply.
- **Open** — the promise still holds. Leave it alone.

**Never act on ignorance.** A lookup that fails returns no verdict, exactly
like an open PR. The cost of doing nothing is a stale lane for fifteen more
minutes; the cost of guessing wrong is completing work a human never accepted,
or re-planning work that shipped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

from services.task_board import (
    BoardSnapshot,
    BoardTask,
    ClaimHeld,
    LaneChanged,
    LeaseLost,
    TaskBoardError,
)

from . import plan_notes, selection
from .plan_notes import PlanDoc

logger = logging.getLogger(__name__)

#: Seconds. Deliberately short — this is bookkeeping, not work, and a claim
#: here blocks the WHOLE board (`any_claim_live` is the basis for
#: one-task-in-flight). If a release is refused mid-reconcile we still hold the
#: claim, so this number is how long that costs before it heals itself.
RECONCILE_LEASE_S = 120

#: The pipeline's own PR links, as `jobs.py` writes them into the notes. Kept
#: permissive on the owner/name charset rather than anchored to a known repo:
#: the board tells us which repo it targets, and hard-coding a list here would
#: quietly stop reconciling the day a board is pointed somewhere new.
_PR_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)/pull/(\d+)")


@dataclass(frozen=True)
class PRRef:
    repo: str
    number: int

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}/pull/{self.number}"


@dataclass(frozen=True)
class PRState:
    """What GitHub says. `state` is OPEN | CLOSED | MERGED."""

    state: str
    merged: bool

    @property
    def is_merged(self) -> bool:
        # Trust either signal. `state` went to MERGED only on newer gh
        # versions; `mergedAt` has always been populated, and a PR that has
        # one without the other is still unambiguously merged.
        return self.merged or self.state.upper() == "MERGED"

    @property
    def is_rejected(self) -> bool:
        return self.state.upper() == "CLOSED" and not self.is_merged


@dataclass(frozen=True)
class Verdict:
    """One task's correction. `lane` is where it goes; `complete` archives it."""

    task_id: str
    pr: PRRef
    lane: str
    complete: bool
    outcome: str
    notes: str


def pr_ref(notes: str) -> Optional[PRRef]:
    """The pull request a task's notes point at, if any.

    First match wins. A task's notes are rewritten wholesale by each job, so
    the only PR URL present is the one that job just opened — but a human is
    free to paste more prose underneath, and taking the first keeps ours.
    """
    m = _PR_URL.search(notes or "")
    if not m:
        return None
    try:
        return PRRef(repo=m.group(1), number=int(m.group(2)))
    except ValueError:  # pragma: no cover — the regex guarantees digits
        return None


def _rejected_notes(task: BoardTask, pr: PRRef) -> str:
    """Notes for a task going back to `replan` after its PR was refused.

    The prior plan and acceptance criteria are preserved — they are still the
    best statement of the intent, and the planner re-reading its own previous
    reasoning is the point of a replan. The rejection goes AFTER the rendered
    document rather than inside it, because `render()` deliberately drops
    `human_text`: residue below the sections is exactly how a human's typed
    reply reaches `plan_notes.parse`, and a closed PR is a reply.
    """
    prior = plan_notes.parse(task.notes or "")
    doc = PlanDoc(
        understanding=(
            "The previous attempt was implemented and refused. Re-planning "
            "with that as the starting point."),
        plan=prior.plan,
        acceptance=prior.acceptance,
        blast_radius=prior.blast_radius,
        # Pass 1: the implement job stamps its own note as pass 1, so this is
        # not resuming a planning conversation — it is starting a new one with
        # a rejection as its input. Carrying a stale count forward could trip
        # `at_pass_cap` and stall a task on its first honest retry.
        pass_number=1,
    )
    return (
        plan_notes.render(doc)
        + "\n\n"
        + f"The pull request for this was CLOSED WITHOUT MERGING: {pr.url}\n"
        "Treat that as a rejection of the previous approach, not as new work. "
        "Work out what was wrong with it before proposing the same thing "
        "again — and if the reason is not visible in the diff or the PR "
        "discussion, ask rather than guess.\n"
    )


def _merged_notes(task: BoardTask, pr: PRRef) -> str:
    """Notes for a task being archived because its PR merged.

    Still rendered rather than blanked: the task is archived, not deleted, and
    the plan is the only record of why the change looks the way it does.
    """
    prior = plan_notes.parse(task.notes or "")
    return plan_notes.render(PlanDoc(
        understanding=f"Merged. {pr.url}",
        plan=prior.plan,
        acceptance=prior.acceptance,
        blast_radius=prior.blast_radius,
        pass_number=1,
    ))


def decide(task: BoardTask, pr: PRRef,
           state: Optional[PRState]) -> Optional[Verdict]:
    """What to do about one `landed` task. Pure.

    `None` means leave it alone, and covers both "the PR is still open" and
    "we could not find out" on purpose — see the module docstring on never
    acting on ignorance.
    """
    if state is None:
        return None
    if state.is_merged:
        return Verdict(task_id=task.id, pr=pr, lane=selection.LANE_LANDED,
                       complete=True, outcome=f"pr-merged:{pr.number}",
                       notes=_merged_notes(task, pr))
    if state.is_rejected:
        return Verdict(task_id=task.id, pr=pr, lane=selection.LANE_REPLAN,
                       complete=False, outcome=f"pr-rejected:{pr.number}",
                       notes=_rejected_notes(task, pr))
    return None


#: Look up one pull request. Returns None when the answer isn't knowable —
#: network, auth, a deleted repo — which `decide` treats as "leave it alone".
Lookup = Callable[[PRRef], Optional[PRState]]


def reconcile(board: BoardSnapshot, client, board_handle: str, *,
              lookup: Lookup) -> list[str]:
    """Bring every `landed` task on one board back in line with its PR.

    Returns one short line per task actioned, for the sweep log. Never raises:
    a board that cannot be reconciled must not stop the board being swept, and
    this runs BEFORE selection precisely so a correction can free work that
    selection would otherwise never see (a rejected task moving to `replan` is
    claimable on the very next tick).
    """
    acted: list[str] = []

    for task in board.tasks_in(selection.LANE_LANDED):
        ref = pr_ref(task.notes or "")
        if ref is None:
            continue

        try:
            state = lookup(ref)
        except Exception as e:  # a lookup must never break the sweep
            logger.warning("reconcile: could not read %s: %s", ref.url, e)
            continue

        verdict = decide(task, ref, state)
        if verdict is None:
            continue

        try:
            token = client.claim(board_handle, task.id,
                                 lease_seconds=RECONCILE_LEASE_S)
        except ClaimHeld:
            # Someone is actively working this task. Whatever they do next
            # will write the lane, and it will be better informed than we are.
            continue
        except TaskBoardError as e:
            logger.warning("reconcile: claim failed on %s: %s", task.id, e)
            continue

        try:
            client.release(
                board_handle, task.id, token,
                lane=verdict.lane, notes=verdict.notes,
                outcome=verdict.outcome, complete=verdict.complete,
                # A human who retagged this between our read and now owns it.
                # A mismatch writes nothing rather than dragging it back.
                if_current_lane=selection.LANE_LANDED,
            )
        except (LaneChanged, LeaseLost) as e:
            logger.info("reconcile: %s moved out from under us (%s)",
                        task.id, type(e).__name__)
            continue
        except TaskBoardError as e:
            logger.error("reconcile: release failed on %s; the claim frees "
                         "itself in %ds: %s", task.id, RECONCILE_LEASE_S, e)
            continue

        acted.append(f"{task.id[:8]}: {verdict.outcome}")
        logger.info("reconcile: %s → %s (%s)",
                    task.id, verdict.lane, verdict.outcome)

    return acted


def gh_lookup(run: Callable[[list], tuple]) -> Lookup:
    """A {@link Lookup} backed by `gh pr view`.

    `run` is the `(argv) -> (ok, stdout)` shape `run_taskauto._gh` already
    uses for the production watcher, reused rather than reinvented so there
    is one way this process shells out to `gh`.

    One call per landed task per sweep, which sounds worse than it is: a task
    only stays `landed` while its PR is open, so everything this touches is
    resolved once and then leaves the lane. Steady state is one call per
    genuinely-open PR — currently one across the whole fleet.

    `gh pr view` rather than a batched `gh pr list --state all`: the batch
    needs a `--limit` that truncates silently, and on a repo with hundreds of
    pull requests the one we care about can fall off the end. Being certain
    about a handful beats being fast and occasionally wrong about whether
    someone's work was merged or thrown away.
    """
    import json as _json

    def look(pr: PRRef) -> Optional[PRState]:
        # `--repo` is explicit, so this needs no checkout to run in.
        ok, out = run(["gh", "pr", "view", str(pr.number), "--repo", pr.repo,
                       "--json", "state,mergedAt"])
        if not ok:
            logger.warning("reconcile: gh pr view %s failed", pr.url)
            return None
        try:
            d = _json.loads(out or "{}")
        except ValueError:
            logger.warning("reconcile: gh pr view %s returned non-JSON", pr.url)
            return None
        return PRState(state=str(d.get("state") or ""),
                       merged=bool(d.get("mergedAt")))

    return look
