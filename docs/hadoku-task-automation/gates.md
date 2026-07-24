# Gates

There is no human between the agent and `main`. These are the only thing standing there.

Read [README.md §4](README.md) first: the safety argument is **not** "these gates are complete."
It's "these gates plus an automatic revert." Gates cut the failure rate; the prod watcher bounds the
blast radius of everything they miss. Designing gates as if they were the last line of defence is
how you end up trusting them too much.

Gate vocabulary, verdicts, and the evidence-store discipline are inherited from
[crimson-kitty/gates.md](../crimson-kitty/gates.md). Two differences:

- **`defer` collapses to `stalled`.** crimson-kitty defers to an operator inbox a human reads at a
  laptop. This pipeline's whole premise is that no such human is available, so a deferred judge
  verdict routes the task to `stalled` with its reasoning in `notes`. Pass/fail only, in effect.
- **`fail` has two destinations.** Before any code is written, a failure means *"I don't understand
  the request"* → `plan-review`, which is a question for you. After code exists, a failure means
  *"the work isn't safe to land"* → `stalled`. Same verdict, different lane, very different meaning
  to someone reading the board on a phone.

---

## The failure classes these exist to kill — and where each gate comes from

Most of this page already exists. Agent-failure classes are agent-failure classes regardless of who
filed the issue, so crimson-kitty's gate set transfers; only the gates that are specifically about
*merging unreviewed* are new.

| # | Failure | Gate | Provenance |
|---|---|---|---|
| 1 | Agent misread the sentence and fixed the wrong thing | `target_resolved` (G1) | **reuse** `gates/actionability.py`, new rubric |
| 2 | "Tests pass" proves nothing — nothing was ever red, or nothing was ever asserted | `verification_possible` (G2) | **reuse** `gates/actionability.py` |
| 2 | ″ | `repro_is_red` (G3) | **reuse** `gates/repro.py` |
| 3 | Empty or no-op change | `diff_non_empty` (G4) | **reuse** `gates/fix.py` unchanged |
| 4 | Agent helpfully refactored 40 unrelated files | `blast_radius_respected` (G5) | **extend** `gates/fix.py` relevance check |
| 5 | Agent edited CI, secrets, migrations, or its own gates | `protected_paths_untouched` (G6) | **new** |
| 6 | Credential committed | `no_secrets_in_diff` (G7) | **new** |
| 7 | Fix doesn't actually fix it | `acceptance_met` (G8) | **reuse** `gates/verify.py` |
| 8 | Fix breaks something else, or `main` moved underneath | `suite_green_on_merge_result` (G9) | **extend** `activities/test_runner.py` |
| 9 | Diff is plausible but answers a different question | `fix_addresses_task` (G10) | **reuse** relevance judge, new rubric |
| 10 | It all passed and prod fell over anyway | G11–13 → **auto-revert** | **new**, polling shape from `issue_workflow_post.py` |
| 11 | Item was already done, or isn't a bug — and got "fixed" anyway | intake dismissal rule (§1.1) | **new**, no gate: routes to `plan-review` |

**Seven of thirteen are existing modules**, three more are extensions, and the four genuinely new
ones (G6, G7, G11–13) all exist for the same reason: crimson-kitty never merged anything. It opened
a PR and let a maintainer decide. Take the maintainer away and you need a deny-list, a secret scan,
and a way to undo — nothing else about the gate set changes.

The two gates that need a genuinely new *rubric* rather than new code are G1 and G10, and for the
same reason: crimson-kitty judges a diff against a rich aggregator brief, while this pipeline judges
it against a sentence you typed on a bus.

---

## Phase A — before any code is written

The cheapest place to stop a task, and the one that makes the phone loop work. Both gates run in
`planning`, before a single agent token is spent on implementation.

The planning agent's output, per item, is `scope/plan.json`:

```jsonc
{
  "repo": "WolffM/tenhands",
  "understanding": "The deploy.yml workflow fails on the pnpm provisioning step since 95075ba …",
  "evidence": [
    "https://github.com/WolffM/tenhands/actions/runs/…  (failing, 3 consecutive)",
    ".github/workflows/deploy.yml:41"
  ],
  "blast_radius": [".github/workflows/deploy.yml"],
  "repro_method": "workflow_run",
  "confidence": 0.86,
  "questions": []
}
```

### G1 · `target_resolved` — judge

Passes when `evidence` is non-empty, `questions` is empty, and `confidence` clears the per-repo
threshold. Otherwise **fail → `plan-review`**, with `understanding` and `questions` written into
`notes`.

This is the gate that reads "fix the production CI workflow bug" and decides whether it found a
specific red run in a specific file, or is about to guess. Guessing is the expensive failure — every
downstream gate is measuring the agent against a target this gate chose. A wrong target passes
every other gate on this page.

Bias it toward asking. A question on your phone costs you fifteen seconds; a confidently wrong
autonomous merge costs an evening.

### G2 · `verification_possible` — mechanical

**This is what makes "on green" mean anything.** If nothing distinguishes the before state from the
after state, a green suite afterwards is evidence of nothing at all — it was green before. But what
counts as verifiable depends on which kind of item this is, and the task text already tells us
(§1.1):

| Item | Passes when | Verified later by |
|---|---|---|
| **`bug-` prefixed** — a claim something is broken | `repro_method != "none"` | G3 red → G8 green, the same artifact |
| **unprefixed** — a change request | the plan declares an **acceptance check**: the observable end state, as a test, a screenshot, or a grep | G8, restated as "the declared end state is now true" |

An earlier draft of this page demanded a reproduction from *everything*, which would have stalled
`make coffee theme default` forever — there is no bug there to reproduce, and demanding one is a
category error. A change request's equivalent of a repro is an acceptance check, and asking for that
is reasonable: *"coffee is the default theme"* is a one-line assertion.

What still fails this gate is an item where neither exists — nothing to reproduce **and** no
statable end condition. `too much wooshing` is the honest example: there's no assertion that makes
it true or false. Those route to `plan-review`, where the question is precisely *"how would you
tell me this was fixed?"*, and your answer becomes the acceptance check. That's not the pipeline
being obtuse — it's the same question you'd have to answer before you could review the diff
yourself.

---

## Phase B — the work exists, it hasn't landed

### G3 · `repro_is_red` — mechanical

The declared reproduction must **actually fail on the pre-fix tree**. Run it, record the output,
assert non-zero.

An agent that reports "reproduced the bug" without a red artifact has reproduced nothing. This gate
is mechanical and unbypassable on purpose: it's the anchor G8 later compares against, so a soft
version of it silently softens the entire verification story.

### G4 · `diff_non_empty` — mechanical

Ported from crimson-kitty unchanged. Commits ahead of base, diff not whitespace-only.

### G5 · `blast_radius_respected` — mechanical

Files touched ⊆ `blast_radius` from `scope/plan.json`, plus test files, plus a per-repo hard cap on
files and lines changed. Exceeding it fails to `stalled`.

Scope creep is the most common way a *correct* fix becomes an unreviewable one. The agent declared
its intended reach before it started; this holds it to that. When the plan was genuinely too narrow,
the right outcome is stalling and re-scoping, not silently widening.

### G6 · `protected_paths_untouched` — mechanical

A per-repo deny-list that never auto-merges. Defaults:

```
.github/workflows/**        self-modifying CI
Dockerfile, docker-compose*, deploy/**, infra/**
.devvault.json, .env*, **/*secret*, **/*.pem
**/migrations/**            destructive and irreversible
package.json, pnpm-lock.yaml, requirements.txt   new dependencies = new supply chain
backend/temporal/**         (tenhands only) the pipeline's own gates
```

That last line matters: an agent that can edit its own gates is not gated. The first four matter
because they're the paths where "reversible by a follow-up commit" stops being true — a broken
migration or a leaked secret does not un-happen when you revert.

**Note the tension with your own motivating example.** *"Fix the production CI workflow bug"* lands
squarely in `.github/workflows/**`. That's not an accident of the list — CI is genuinely the thing
you least want an unreviewed agent rewriting, because a broken deploy workflow can break the very
mechanism that would ship the revert.

The escape hatch is a per-task authorisation, not a global exemption: a task carrying

```
allow-protected: .github/workflows/deploy.yml
```

lets the agent touch exactly that path, because a human authorised that specific blast radius.

**But the obvious way to build this is a privilege escalation, and it took a second pass to see it.**
If the gate reads `allow-protected:` out of `notes`, then the *planning agent* — which rewrites
`notes` on every pass — can grant itself permission to edit CI, the vault manifest, or its own
gates. The deny-list would be enforcing nothing. An agent that can write its own authorisation is
not authorised, it is unsupervised.

Two mechanical fixes, and we want both:

1. **Snapshot `notes` at claim time.** Only directives present in the pre-claim snapshot count. The
   agent can write whatever it likes into `notes` afterwards; the gate reads the frozen copy, and
   the human's version is the only one with authority.
2. **Accept the directive in the task *title* too**, which the agent never rewrites. Belt and
   braces, and it's the more natural place to type it on a phone anyway.

The general rule this is an instance of: **no gate may read its own authorisation from a field the
agent can write.** Worth checking every future gate against, because this one looked completely
reasonable until it didn't.

### G7 · `no_secrets_in_diff` — mechanical

Secret scan over the diff. Hard fail, never overridable, no `allow-` escape hatch. A committed
credential is the one failure on this page that a revert does not undo — the value is burned the
moment it's pushed, and the remedy is rotation, not git.

### G8 · `acceptance_met` — mechanical

For a `bug-` item: the exact artifact that was red in G3 is now green — same command, same runner,
same assertion. For a change request: the acceptance check declared at G2 now holds.

G3 and G8 are one gate split across time, and they're the core of the whole design: *this specific
thing was broken, and now this specific thing is fixed.* Every other gate on this page is a
safety rail around that claim.

### G9 · `suite_green_on_merge_result` — mechanical

Full suite, typecheck, lint, and build — run on the **merge commit against current `main`**, not on
the branch in isolation.

Merge-queue semantics, and worth the extra minutes: a branch cut an hour ago passes against the
`main` it remembers, not the one it's about to land on. Since the agent already works in a
worktree, merging `main` in and running there is nearly free.

Per your working agreement: warnings are errors here. A gate that tolerates warnings tolerates
whatever the next warning turns out to mean.

### G10 · `fix_addresses_task` — judge

The one LLM call in the pipeline. Reuses `judge.py` with a new rubric: given the sentence you typed,
the plan, and the final diff — does this do what was asked, and only that?

It's the check no mechanical gate can make. G1–G9 verify that *something* was broken, is now fixed,
and nothing else moved; none of them verify it's the thing **you** meant. Deferred verdicts route to
`stalled` (there's no inbox to defer into).

---

## Phase C — it landed, and now we watch

### G11 · `deploy_succeeded` · G12 · `health_green` — mechanical watchers

After the merge: watch the deploy run to conclusion, then poll the service's health signal for a
fixed window (10–15 min, per repo). Red deploy, red health, or an error-rate spike → G13.

### G13 · `auto_revert` — compensating action, not a gate

`git revert` the merge commit, push, move the task to `stalled` with the deploy log and health
output in `notes`.

This is the load-bearing safety property, and it's why the rest of this page is allowed to be
imperfect. Every landing is reversible by a follow-up commit, automatically, without your phone.

Two honest limits:

- **Revert is not undo** for anything that escaped the repo — a run migration, a published package,
  a sent webhook, a rotated secret. G6 exists to keep those paths out of the autonomous flow
  precisely because G13 can't clean up after them.
- **The watcher can only see what the repo exposes.** A repo with no health signal gets no G12, and
  therefore no auto-revert trigger — which is exactly the per-repo eligibility bar in
  [README.md §4](README.md), restated from the other end.

---

## Remediation yes, review agent no

Two things get conflated here, and they deserve opposite answers.

**A capped remediation loop: yes, and it's load-bearing.** When a gate fails there are only two
options — stall and wait for a human, or let the agent try again with the gate's complaint as
input. Since the entire premise is "land it without me," remediation is the thing that keeps the
stall rate low enough for the pipeline to be worth having. Without it, every flaky test and every
lint nit becomes a task waiting on your laptop.

So: gate fails → feed the failure back to the agent → re-run the gates → repeat, capped at 3 → and
if it's still failing, `stalled` with the full history. That's `gates/remediation.py` and
crimson-kitty's `_MAX_LOCAL_REMEDIATION_ITERATIONS`, reused as-is.

**A separate review agent: no.** On someone else's repo, a review pass substitutes for the
maintainer's judgement about house style and hidden constraints. On your own repo with a green
suite, it mostly generates opinions — and every one it raises has to be adjudicated by something,
which in an unattended pipeline means either auto-accepting its advice (letting an LLM's taste
rewrite working code) or stalling on it (defeating the point).

The gates already *are* the review, and they're better than an LLM review for this job because they
fail on facts: the repro is green, the suite passes on the merge result, the diff stayed inside the
declared blast radius. The one genuinely judgement-shaped question — *did this do what was asked* —
is G10, and it's one call, not a loop.

**Trigger remediation on evidence, not on plan size.** The instinct to add review "for bigger
plans" is measuring the wrong thing: a large mechanical rename is safer than a three-line change to
auth. A gate that actually failed is a fact; "this plan looked big" is a guess. If it turns out that
large diffs stall more often, that's a reason to tighten G5's caps at planning time — a smaller
blast radius per task — rather than to add a reviewer at the end.

## Tuning

Every threshold on this page is per-repo config, not a constant: G1's confidence bar, G5's file and
line caps, G6's deny-list, G9's command set, G12's watch window.

Start strict. The failure mode of a strict gate is a task in `stalled` that you fix on a laptop —
annoying, recoverable, visible on the board. The failure mode of a loose gate is a silent bad merge
into a repo you weren't watching. Loosen from evidence once the pipeline has landed a few dozen
tasks and the stall reasons are boring.
