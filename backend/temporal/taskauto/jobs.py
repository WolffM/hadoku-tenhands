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
import time
from pathlib import Path
from typing import Callable, Optional

from . import github_item, plan_notes, selection
from .agent import AgentError, ClaudeCodeAgent
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
{item_block}{notes_block}
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
- Do not invent a reason for the task. If no review feedback, failing check or
  complaint is shown above, none exists — plan for what IS there, and never
  write a step or an acceptance check about something you have not been shown.
- If a GitHub item is quoted above, that is its full text. Do not ask a human
  to paste back what is already in front of you.
"""

IMPLEMENT_PROMPT = """\
You are the implementation step of an automated pipeline, working in a
checkout that is yours. Make the change described below. Nobody will review
your diff before it merges, so correctness matters more than speed.

TASK: {title}

{plan}
{human_block}
Rules:
- Change ONLY what the plan's blast radius describes. Unrelated cleanup will
  fail a gate and stall the task.
- Do NOT commit, branch, push, or touch git at all — the pipeline commits.
- Make the acceptance check under "How we'll know it worked" true.
- If you conclude the change should not be made, make no edits and say why.
"""


#: How much of the agent's own account to keep. It is the only description of
#: what was actually built, and on a refusal it is the thing that tells you
#: whether you want the change at all — but `notes` is read on a phone.
AGENT_LOG_CHARS = 1200


def _refusal_advice(reason: str) -> str:
    """One line on why this class of refusal exists. Not an escape hatch.

    It used to end with instructions for `allow-protected:` — put it in the
    TITLE, not the notes, and here is why. That was accurate and useless: an
    override you have to remember an exact incantation for, on a phone, months
    after reading about it, is not an override anyone will reach for. Either
    the pipeline may touch these paths or it may not, and it may not.

    So this says why it stopped and stops. The human's move is to make the
    change themselves, or to reword the task so it does not need those paths.
    """
    r = reason.lower()
    if "manifest change refused" in r:
        return ("A version bump or a range move on a dependency that is "
                "already there lands on its own. This one did something a "
                "revert does not undo cheaply — introduced a dependency, "
                "pointed one outside the registry, or added a script that "
                "runs on every install — so it needs a human.")
    if "protected path" in r or "allow-protected" in r:
        return ("These paths — CI, secrets, migrations, and this pipeline's "
                "own code — are the ones a bad merge cannot be undone by a "
                "revert, so nothing automated may touch them. This part "
                "needs a human.")
    if "blast radius" in r:
        return ("A correct fix this wide is still an unreviewable one. Split "
                "the task, or raise `max_files_changed` for this repo.")
    if "test" in r or "suite" in r:
        return ("Nothing else reads this diff before it merges, so the suite "
                "is the only thing between a bad change and `main`.")
    return ""


def _stall_note(doc: PlanDoc, *, trailing: str, questions: Optional[list] = None,
                agent_said: str = "", changed_files: Optional[list] = None) -> str:
    """A stall note that does not throw away the plan it stalled on.

    **The plan leads and the failure trails.** An earlier version put the
    refusal in `## What I think you want`, which is the first thing rendered —
    so a task whose plan was fine read as though the plan were the problem.
    What stopped is a fact *about* the document, not the document, so it goes
    below everything via `plan_notes.with_trailing_note`.

    Both stall paths used to build a FRESH `PlanDoc`, which meant the approved
    plan vanished from `notes` — and `notes` is the only place it lives. The
    cost was not cosmetic: `implement_job` starts with `if not doc.plan: ->
    LANE_REPLAN`, so a human who did the obvious thing and re-approved a
    stalled task got the whole planning conversation restarted from scratch.
    On the `meet` task that was 266 seconds of planning across three passes,
    discarded because a gate said no to one file.

    So the plan, its acceptance check and the pass number are carried through
    verbatim. What changes is the framing: what stopped, why, and what the
    human can do — plus the agent's own account, which is the only record of
    what was built and is otherwise dropped on the floor.
    """
    if agent_said.strip():
        trailing = (f"{trailing}\n\nWhat I built before stopping:\n"
                    f"{agent_said.strip()[-AGENT_LOG_CHARS:]}")
    rendered = plan_notes.render(PlanDoc(
        understanding=doc.understanding,
        plan=doc.plan,
        questions=questions or [],
        settled=doc.settled,
        acceptance=doc.acceptance,
        blast_radius=list(changed_files) if changed_files else doc.blast_radius,
        pass_number=doc.pass_number,
    ))
    return plan_notes.with_trailing_note(rendered, trailing)


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
                  *, base_branch: str = "main",
                  hydrate: Callable[[str, str], str] = github_item.hydrate):
    """A `plan` job bound to a specific agent and checkout manager.

    `hydrate(repo, title)` re-fetches the GitHub issue or PR a task was seeded
    from and returns it as prompt text — "" when the task has no item behind
    it. It runs HERE, in the trusted parent, precisely because the agent it
    feeds cannot do it: planning holds no `gh` and no token by design
    (`agent.py`), and the board notes it would otherwise rely on carry a
    280-character preview of the item. See `github_item` for what that cost.
    """

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

        # Before the notes, not after: the notes' preview of a seeded item is
        # a lossy copy of what this returns, and the prompt tells the agent to
        # prefer this one.
        item_block = hydrate(board.repo, pickup.task.title)
        if item_block:
            item_block = f"\n{item_block}\n"
        sink.heartbeat()

        notes_block = ""
        if pickup.task.notes.strip():
            notes_block = (
                f"\nWHAT'S ALREADY IN THE TASK NOTES (including anything the "
                f"human replied):\n---\n{pickup.task.notes.strip()}\n---\n")

        t0 = time.monotonic()
        raw = agent.ask(checkout, PLAN_PROMPT.format(
            title=pickup.task.title,
            kind="a bug report — it claims something is broken"
                 if kind.is_bug else "a change request",
            item_block=item_block,
            notes_block=notes_block,
            verify_hint="For a bug, this is what shows it is broken TODAY."
                        if kind.is_bug else
                        "State it so it is unambiguously true or false.",
        ))
        # Agent time only: the clock stops when the subprocess returns, so CI
        # and the human's thinking time are never counted.
        sink.record(plan_s=time.monotonic() - t0, plan_passes=1)
        sink.heartbeat()

        # `parse` never raises, so a reply that is not a document at all
        # arrives here as an empty `PlanDoc` and falls into the
        # `no-action-proposed` branch below — which tells the human this
        # looks already done. That is a verdict, and we did not have one.
        # Refuse to infer anything from a reply we could not read.
        if not plan_notes.has_known_section(raw):
            raise AgentError(
                "the planning reply contained none of the expected sections; "
                f"it began: {raw.strip()[:200]!r}")

        doc = plan_notes.parse(raw)
        # A first plan is pass 1. `parse("")` reports 1 for raw capture, so
        # incrementing unconditionally labelled the first plan "pass 2" and
        # burned a round off the cap before the conversation had started.
        doc.pass_number = (
            1 if plan_notes.looks_unplanned(pickup.task.notes or "")
            else prior.pass_number + 1)
        doc.settled = prior.settled

        if not doc.plan and not doc.questions:
            # Neither a plan nor a question, in a document we could read.
            # Usually "already done" — which we must never conclude
            # unilaterally, so it goes to the human. This branch is only
            # honest because of the check above: it now means the agent
            # proposed nothing, not that we failed to understand it.
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
            # No plan to implement. The usual cause is OURS, not the human's:
            # a planning pass that asked a question instead of writing a plan
            # (see `plan:unverifiable`) parks the task in `plan-review` with
            # questions and no `## Plan`, and approving from there is the
            # obvious thing to do. Send it to `replan`, not `plan-review`:
            # the pipeline claims from `replan`, so the next tick plans it and
            # the task heals itself.
            #
            # This used to go to `plan-review` and ask "should this go back
            # through planning?". That lane is terminal for the pipeline, so
            # nothing would ever pick the task up again, and the question could
            # not be answered by answering it — only by dragging the task
            # somewhere else. A question whose answer is a lane change should
            # be the lane change.
            return (selection.LANE_REPLAN,
                    plan_notes.render(PlanDoc(
                        understanding=(
                            "There was no plan here to implement — my last "
                            "pass asked a question instead of writing one. "
                            "I've put this back in `replan` and will plan it "
                            "on the next pass. Nothing is needed from you."),
                        pass_number=1)),
                    "implement:no-plan")

        # Anything the human wrote that we didn't. `render` deliberately emits
        # only the sections we control, so without this the approve path
        # silently drops their words: a person who answers a question and drags
        # straight to `approved` — rather than through `replan` — would watch
        # the agent implement the unamended plan. The planning path never had
        # this hole; it hands the raw notes over verbatim.
        human_block = ""
        if doc.human_text.strip():
            human_block = (
                "\nWHAT THE HUMAN WROTE ALONGSIDE THIS PLAN. They approved it "
                "with this in the notes, so treat it as amending the plan "
                "above, and prefer it wherever the two disagree:\n"
                f"---\n{doc.human_text.strip()}\n---\n"
            )

        t0 = time.monotonic()
        outcome = agent.work(checkout, IMPLEMENT_PROMPT.format(
            title=strip_bug_prefix(pickup.task.title),
            plan=plan_notes.render(doc),
            human_block=human_block,
        ))
        sink.record(implement_s=time.monotonic() - t0, implement_runs=1)
        sink.heartbeat()

        if not outcome.made_changes:
            return (selection.LANE_STALLED,
                    _stall_note(
                        doc,
                        trailing=("**NOT LANDED — the agent made no changes, "
                                  "so there was nothing to land.**"),
                        agent_said=outcome.log,
                        changed_files=[]),
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
                # The manifest rule reads this when the checkout cannot be
                # consulted; with a checkout the exact form wins anyway.
                diff_text=outcome.diff,
            )
        except LandingRefused as e:
            return (selection.LANE_STALLED,
                    _stall_note(
                        doc,
                        trailing=(
                            "**NOT LANDED — refused at the landing gate.**\n\n"
                            f"{str(e)[:1200]}\n\n"
                            f"{_refusal_advice(str(e))}").strip(),
                        agent_said=outcome.log,
                        changed_files=outcome.changed_files),
                    "land:refused")

        if res.pr_url:
            # PR mode: the work is done, which is a success and must not read
            # as a dry run. `pushed` is False here by design — nothing reached
            # `main` — so this branch has to come first, before the not-pushed
            # check below. Whether it still needs a human is the one thing the
            # note must get right; reconciliation archives it either way once
            # the PR actually merges.
            status = (
                "Implemented and pushed as a pull request. NOT merged yet — "
                "auto-merge is armed, so GitHub lands it when the required "
                f"checks go green.\n\n{res.pr_url}\n\n"
                "Nothing to do unless the checks go red or the diff reads "
                "wrong, in which case close it."
                if res.auto_merge_armed else
                "Implemented and pushed as a pull request. NOT merged — this "
                f"is waiting on you.\n\n{res.pr_url}\n\n"
                "Merge it if the checks are green and the diff reads right.")
            # Status goes under Outcome; the understanding the human approved is
            # carried through unchanged, and the execution log stays under Plan
            # while the task is in flight (reconciliation drops it on merge).
            return (pr_lane,
                    plan_notes.render(PlanDoc(
                        outcome=status, understanding=doc.understanding,
                        plan=res.checks, acceptance=doc.acceptance,
                        blast_radius=outcome.changed_files, pass_number=1)),
                    f"pr-open:{res.pr_url.rsplit('/', 1)[-1]}")

        if not res.pushed:
            return (selection.LANE_PLAN_REVIEW,
                    plan_notes.render(PlanDoc(
                        outcome="Verified but NOT pushed (dry run).",
                        understanding=doc.understanding,
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
                                outcome="Landed, then production went red — "
                                        "and could not be reverted "
                                        "automatically.",
                                understanding=doc.understanding,
                                plan=checks, pass_number=1)),
                            "landed:unwatched-red")
                rev = reverter.revert(checkout, res.commit_sha,
                                      base=base_branch)
                checks.append(f"REVERTED as {rev[:8]}")
                return (selection.LANE_STALLED,
                        plan_notes.render(PlanDoc(
                            outcome=("Landed, production went red, and the "
                                     "change was reverted."),
                            understanding=doc.understanding,
                            plan=checks,
                            questions=[verdict.reason],
                            blast_radius=outcome.changed_files,
                            pass_number=1)),
                        f"reverted:{res.commit_sha[:8]}")
        else:
            checks.append("NO PROD WATCHER — nothing is watching this change")

        return (selection.LANE_LANDED,
                plan_notes.render(PlanDoc(
                    outcome="Landed and production stayed healthy."
                            if watcher and health_url else "Landed.",
                    understanding=doc.understanding,
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
