Review and land the open `taskauto/*` pull requests on a repo.

Usage:
- `/taskauto-prs` — every repo driven by an automation board
- `/taskauto-prs WolffM/hadoku_site` — one repo
- `/taskauto-prs WolffM/hadoku-conjure --watch` — also follow CI after merging

These PRs come from the hadoku-task-automation pipeline: a task was typed on a
board, planned by an agent, approved by a human, implemented, and pushed as a
branch. **The merge is the human gate — it is the only step the pipeline
deliberately does not do.** Treat that as the point of the exercise, not a
formality.

## 1. Find them

Never hardcode a repo list. The repos are whatever boards are shared with the
service key:

```bash
node ../hadoku_site/scripts/secrets/dev-vault.mjs -- .venv/bin/python -c "
import sys; sys.path.insert(0,'backend')
from services.task_board import TaskBoardClient
print([b.repo for b in TaskBoardClient().automation_boards()])"
```

Then per repo:

```bash
gh pr list --repo <repo> --state open \
  --json number,title,url,headRefName,additions,deletions,changedFiles,mergeStateStatus,statusCheckRollup \
  --jq '.[] | select(.headRefName | startswith("taskauto/"))'
```

The branch is `taskauto/<task-ulid-prefix>`. That ULID is the task the PR came
from — use it to read the plan the human approved.

## 2. Review each one against its own plan

This is the part that matters, and it is not "does the diff look fine". Each
plan carries a **How we'll know it worked** section with acceptance criteria
the planning agent wrote, and a **Blast radius**. Check the diff against those:

- Does it satisfy the stated acceptance criteria?
- Does it stay inside the stated blast radius? Files outside it are the single
  most common reason to send one back — the plan is what the human approved,
  and a change beyond it was not approved by anyone.
- If the human added text under `## Questions`, does the diff honour it? That
  amendment outranks the plan.

Read the diff with `gh pr diff <n> --repo <repo>`.

## 3. Decide

**Merge** when it satisfies the plan, checks pass, and `mergeStateStatus` is
`CLEAN`:

```bash
gh pr merge <n> --repo <repo> --squash --delete-branch
```

**Send it back** when it does not. Do not fix it yourself in the PR — that
silently converts an automated change into a hand-written one and the next run
will not know. Move the task to `stalled` with the reason in `notes`, or leave
a PR review comment and say so in your report.

Never merge:
- a red or pending check, unless the human says otherwise
- anything touching CI, secrets, migrations, infra, or the pipeline's own code
  — G6 refuses these for a reason and a human merging by hand bypasses it
- more than you were asked to. One repo means one repo.

## 4. With `--watch`, follow the deploy

Merging is not landing. After each merge:

```bash
gh run list --repo <repo> --limit 5
gh run watch <run-id> --repo <repo>   # or poll until conclusion
```

Report the deploy conclusion per merged PR. If one goes red, say which PR, link
the failing run, and stop merging the rest of that repo — a red deploy plus more
merges is how you lose the ability to attribute the failure.

## 5. Report

Per PR: repo, number, title, the task it came from, merged or sent back, and
why. Then what is left waiting and why. Be concrete about the ones you refused
— that list is more useful than the ones that sailed through.
