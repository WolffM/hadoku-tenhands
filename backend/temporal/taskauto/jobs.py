"""The two jobs a runner can dispatch: `plan` and `implement`.

Each takes `(pickup, board, sink)` and returns `(destination_lane, notes,
outcome)`. Raising is fine — the runner routes failures to `stalled` with the
reason, so neither of these needs its own error handling for the unexpected.

The split matters: **planning cannot edit files** (it uses the read-only
agent call) and **implementing cannot decide whether the work was wanted**
(that was settled when the human moved the task to `approved`). Keeping those
capabilities apart is cheaper than granting both and relying on a prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import plan_notes, selection
from .agent import ClaudeCodeAgent
from .checkout import CheckoutManager
from .landing import Lander, LandingRefused
from .plan_notes import PlanDoc
from .refs import RepoPolicy, TaskRef
from .task_text import classify, strip_bug_prefix
from .watch import ProdWatcher, Reverter

logger = logging.getLogger(__name__)

PLAN_PROMPT = """\
You are the planning step of an automated pipeline. A human typed one short
task onto a board for the repo you are sitting in. Your job is to work out
what they meant and write a plan — you must NOT edit any files.

TASK TITLE: {title}
KIND: {kind}
{notes_block}
Read enough of the repo to be concrete. Then reply with EXACTLY this markdown
and nothing else:

## What I think you want

<one short paragraph, in their terms>

## Plan

1. <step>

## Questions

<numbered questions ONLY if you genuinely cannot proceed without an answer.
If you have none, write exactly: _No open questions._>

## How we'll know it worked

- <an observable end state: a test that passes, a grep that matches, a
  command whose output changes. {verify_hint}>

## Blast radius

- <each file you expect to touch, repo-relative>

Rules:
- Prefer asking to guessing. A wrong guess costs an unreviewed bad merge.
- If the task appears ALREADY DONE, say so in "What I think you want" and put
  the evidence in "How we'll know it worked", with no plan steps.
- Keep the blast radius as small as honestly possible.
"""

IMPLEMENT_PROMPT = """\
You are the implementation step of an automated pipeline, working in a
checkout that is yours. Make the change described below. Nobody will review
your diff before it merges, so correctness matters more than speed.

TASK: {title}

{plan}

Rules:
- Change ONLY what the plan's blast radius describes. Unrelated cleanup will
  fail a gate and stall the task.
- Do NOT commit, branch, push, or touch git at all — the pipeline commits.
- Make the acceptance check under "How we'll know it worked" true.
- If you conclude the change should not be made, make no edits and say why.
"""


def _task_ref(pickup, board, policy: Optional[RepoPolicy] = None) -> TaskRef:
    return TaskRef(
        repo_slug=board.repo,
        board=board.handle or board.id,
        task_id=pickup.task.id,
        title=pickup.task.title,
        # The claim-time snapshot: notes as they stood before we could write.
        notes_at_claim=pickup.task.notes,
        policy=policy or RepoPolicy(),
    )


def make_plan_job(agent: ClaudeCodeAgent, checkouts: CheckoutManager,
                  *, base_branch: str = "main"):
    """A `plan` job bound to a specific agent and checkout manager."""

    def plan_job(pickup, board, sink):
        checkout = checkouts.reset_to(board.repo, base_branch)
        sink.heartbeat()

        prior = plan_notes.parse(pickup.task.notes or "")
        kind = classify(pickup.task.title)

        if prior.pass_number >= plan_notes.MAX_PASSES:
            # Converging is the point; a fourth round of questions is a sign
            # the medium is wrong, not that one more question will help.
            return (selection.LANE_STALLED,
                    plan_notes.render(PlanDoc(
                        understanding=prior.understanding,
                        questions=prior.questions,
                        plan=prior.plan,
                        pass_number=prior.pass_number,
                    )) + "\n_Planning hit its pass cap — this needs a laptop._\n",
                    "plan:cap-reached")

        notes_block = ""
        if pickup.task.notes.strip():
            notes_block = (
                f"\nWHAT'S ALREADY IN THE TASK NOTES (including anything the "
                f"human replied):\n---\n{pickup.task.notes.strip()}\n---\n")

        raw = agent.ask(checkout, PLAN_PROMPT.format(
            title=pickup.task.title,
            kind="a bug report — it claims something is broken"
                 if kind.is_bug else "a change request",
            notes_block=notes_block,
            verify_hint="For a bug, this is what shows it is broken TODAY."
                        if kind.is_bug else
                        "State it so it is unambiguously true or false.",
        ))
        sink.heartbeat()

        doc = plan_notes.parse(raw)
        # A first plan is pass 1. `parse("")` reports 1 for raw capture, so
        # incrementing unconditionally labelled the first plan "pass 2" and
        # burned a round off the cap before the conversation had started.
        doc.pass_number = (
            1 if plan_notes.looks_unplanned(pickup.task.notes or "")
            else prior.pass_number + 1)
        doc.settled = prior.settled

        if not doc.plan and not doc.questions:
            # Neither a plan nor a question. Usually "already done" — which we
            # must never conclude unilaterally, so it goes to the human.
            return (selection.LANE_PLAN_REVIEW, plan_notes.render(doc),
                    "plan:no-action-proposed")

        if doc.has_open_questions:
            return (selection.LANE_PLAN_REVIEW, plan_notes.render(doc),
                    "plan:questions")

        if not doc.acceptance:
            # G2: without an acceptance check there is nothing to verify, and
            # "lands on green" would be an empty phrase.
            doc.questions = ["How would you tell me this was fixed? I could "
                             "not state an acceptance check for it."]
            return (selection.LANE_PLAN_REVIEW, plan_notes.render(doc),
                    "plan:unverifiable")

        # A plan with no questions and a real acceptance check. The human
        # still sees it in plan-review before anything is built — the fast
        # path in the design releases to `approved`, but that is a judgement
        # this job is not yet trusted to make unattended.
        return (selection.LANE_PLAN_REVIEW, plan_notes.render(doc),
                "plan:ready")

    return plan_job


def make_implement_job(agent: ClaudeCodeAgent, checkouts: CheckoutManager,
                       lander: Lander, *, base_branch: str = "main",
                       test_command=None, policy: Optional[RepoPolicy] = None,
                       test_cwd: str = ".",
                       watcher: Optional[ProdWatcher] = None,
                       reverter: Optional[Reverter] = None,
                       health_url: str = "", watch_window_s: int = 600,
                       pr_lane: str = selection.LANE_LANDED):
    """An `implement` job. `lander.dry_run` decides whether it really pushes.

    `pr_lane` is where a task goes once its pull request is open, and `landed`
    is now honestly that lane rather than a stopgap: `autoland` v2 redefined it
    as "The pull request is open, gates green, and waiting on you. Review it
    and merge." The lane that used to mean *merged and production verified*
    means *yours to merge* — which is the same change this module makes, said
    in the vocabulary the board publishes. The notes still give the URL and say
    NOT merged, because a lane name is not evidence.
    """

    def implement_job(pickup, board, sink):
        task = _task_ref(pickup, board, policy)
        checkout = checkouts.reset_to(board.repo, base_branch)
        # Housekeeping before the work, not after: a run that crashes or is
        # killed never reaches its own cleanup, so cleaning at the START is
        # what actually keeps the clone from growing without bound. reset_to
        # has just moved HEAD to the base branch, so last run's branch is now
        # deletable.
        try:
            checkouts.prune(board.repo, base=base_branch)
        except Exception as e:  # never fail a task over tidying
            logger.warning("prune failed on %s: %s", board.repo, e)
        sink.heartbeat()

        # Recovery after a crash between push and release. Observed for real:
        # the runner was killed mid-watch, the commit was already on main, and
        # the task sat in `landing` — a naive re-run would rebuild a change
        # that had already shipped and then stall on "no changes".
        #
        # The commit subject is deterministic from the title, so ask git
        # rather than keeping side-state that can itself be lost.
        already = _already_landed(checkouts, checkout, pickup.task.title,
                                  base_branch)
        if already:
            return (selection.LANE_LANDED,
                    plan_notes.render(PlanDoc(
                        understanding=(
                            f"Already landed as {already[:8]} — recovered a run "
                            f"that was interrupted after the push."),
                        pass_number=1)),
                    f"recovered:{already[:8]}")

        doc = plan_notes.parse(pickup.task.notes or "")
        if not doc.plan:
            return (selection.LANE_PLAN_REVIEW,
                    plan_notes.render(PlanDoc(
                        understanding="I was asked to implement this but the "
                                      "notes carry no plan.",
                        questions=["Should this go back through planning?"],
                        pass_number=1)),
                    "implement:no-plan")

        outcome = agent.work(checkout, IMPLEMENT_PROMPT.format(
            title=strip_bug_prefix(pickup.task.title),
            plan=plan_notes.render(doc),
        ))
        sink.heartbeat()

        if not outcome.made_changes:
            return (selection.LANE_STALLED,
                    plan_notes.render(PlanDoc(
                        understanding="The agent made no changes.",
                        questions=["It said:\n" + outcome.log[-1200:]],
                        pass_number=1)),
                    "implement:no-changes")

        sink.lane(selection.LANE_LANDING)
        try:
            res = lander.land(
                checkout, task,
                branch=f"taskauto/{pickup.task.id[:12].lower()}",
                message=_commit_message(pickup.task.title, doc),
                changed_files=outcome.changed_files,
                base=base_branch,
                test_command=test_command,
                test_cwd=test_cwd,
            )
        except LandingRefused as e:
            return (selection.LANE_STALLED,
                    plan_notes.render(PlanDoc(
                        understanding="The change was built but refused at the "
                                      "landing gate.",
                        questions=[str(e)[:1500]],
                        blast_radius=outcome.changed_files,
                        pass_number=1)),
                    "land:refused")

        if res.pr_url:
            # PR mode: the work is done and waiting on a human, which is a
            # success and must not read as a dry run. `pushed` is False here
            # by design — nothing reached `main` — so this branch has to come
            # first, before the not-pushed check below.
            return (pr_lane,
                    plan_notes.render(PlanDoc(
                        understanding=(
                            "Implemented and pushed as a pull request. NOT "
                            "merged — this is waiting on you.\n\n"
                            f"{res.pr_url}\n\n"
                            "Merge it if the checks are green and the diff "
                            "reads right."),
                        plan=res.checks, acceptance=doc.acceptance,
                        blast_radius=outcome.changed_files, pass_number=1)),
                    f"pr-open:{res.pr_url.rsplit('/', 1)[-1]}")

        if not res.pushed:
            return (selection.LANE_PLAN_REVIEW,
                    plan_notes.render(PlanDoc(
                        understanding="Verified but NOT pushed (dry run).",
                        plan=res.checks, acceptance=doc.acceptance,
                        blast_radius=outcome.changed_files, pass_number=1)),
                    "dry-run")

        # It's on main. From here the only thing that makes an unreviewed
        # landing acceptable is being able to take it back, so watch and
        # revert rather than declaring success on the strength of a push.
        checks = list(res.checks)
        if watcher and health_url:
            sink.heartbeat()
            verdict = watcher.watch(board.repo, res.commit_sha,
                                    health_url=health_url,
                                    window_s=watch_window_s)
            checks.append(f"prod watch: {verdict.reason}")
            if verdict.should_revert:
                if reverter is None:
                    checks.append("NO REVERTER CONFIGURED — prod is red and "
                                  "this change was NOT taken back")
                    return (selection.LANE_STALLED,
                            plan_notes.render(PlanDoc(
                                understanding="Landed, then production went "
                                              "red — and could not be "
                                              "reverted automatically.",
                                plan=checks, pass_number=1)),
                            "landed:unwatched-red")
                rev = reverter.revert(checkout, res.commit_sha,
                                      base=base_branch)
                checks.append(f"REVERTED as {rev[:8]}")
                return (selection.LANE_STALLED,
                        plan_notes.render(PlanDoc(
                            understanding=("Landed, production went red, and "
                                           "the change was reverted."),
                            plan=checks,
                            questions=[verdict.reason],
                            blast_radius=outcome.changed_files,
                            pass_number=1)),
                        f"reverted:{res.commit_sha[:8]}")
        else:
            checks.append("NO PROD WATCHER — nothing is watching this change")

        return (selection.LANE_LANDED,
                plan_notes.render(PlanDoc(
                    understanding="Landed and production stayed healthy."
                                  if watcher and health_url else "Landed.",
                    plan=checks, acceptance=doc.acceptance,
                    blast_radius=outcome.changed_files, pass_number=1)),
                f"landed:{res.commit_sha[:8]}")

    return implement_job


def _already_landed(checkouts, checkout, title: str, base: str) -> str:
    """The sha on `origin/base` whose subject matches this task, or "".

    Matched on the exact subject line rather than a substring search, so a
    task whose title merely appears inside another commit's body doesn't
    read as landed.
    """
    subject = _subject(title)
    runner = getattr(checkouts, "run", None)
    if runner is None:
        return ""
    res = runner(["git", "-C", str(checkout), "log", f"origin/{base}",
                  "--fixed-strings", f"--grep={subject}", "--format=%H%x00%s",
                  "-20"], timeout=60)
    if not getattr(res, "ok", False):
        return ""
    for line in (getattr(res, "out", "") or "").splitlines():
        sha, _, subj = line.partition("\x00")
        if subj.strip() == subject:
            return sha.strip()
    return ""


def _subject(title: str) -> str:
    subject = strip_bug_prefix(title).strip()
    if len(subject) > 68:
        subject = subject[:65].rstrip() + "\u2026"
    return subject


def _commit_message(title: str, doc: PlanDoc) -> str:
    subject = _subject(title)
    body = "\n".join(f"- {s}" for s in doc.plan[:8])
    return f"{subject}\n\n{body}\n"
