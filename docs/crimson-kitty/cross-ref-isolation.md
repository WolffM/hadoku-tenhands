# Cross-reference isolation

## Why this exists

GitHub auto-generates a cross-reference **notification** to upstream maintainers
the instant any public artifact mentions their issue — a full URL, an
`owner/repo#N` short ref, or a `Fixes #N` keyword is all it takes. A fork is
public and permanently linked to its parent, so every commit message, PR title,
and issue body an agent writes on our fork is one stray reference away from
pinging a maintainer about work that may still be half-finished, wrong, or
destined to be aborted by a gate.

That's the failure mode this design removes. Maintainers should hear from this
pipeline exactly once: when a human operator has reviewed the finished work and
explicitly submitted it. **No notification reaches a maintainer until the
operator submits.** The point is courtesy — don't spam maintainers with
unfinished agent work — not concealment: the forks are public, the branches are
readable, and the submitted PR says exactly what it is.

In jade-hare, three of these accidental notifications fired (the leak vectors
below). The structural fix in crimson-kitty: **the agent never sees the real
upstream issue identifier**. We strip every URL, slash-form short ref, and bare
issue number from the brief before passing it to Copilot. The agent fixes the
bug without knowing what number to write back. With the input sanitized, the
only remaining leak surface is anything the agent *invents* from training
data — and invented refs that don't correspond to a real upstream issue can't
fire a cross-reference. Upstream is linked in exactly one place: the PR the
operator approves at submission.

This is the "untrust the agent" principle made concrete.

## How GitHub auto-creates cross-references

GitHub fires a notification on `upstream/repo#N` whenever a public artifact
references it via:

1. **Full URL** — `https://github.com/upstream/repo/issues/N` or `/pull/N`
2. **Slash short ref** — `upstream/repo#N`
3. **Auto-close keyword in a PR against the parent** — `Fixes #N`, `Closes #N`,
   `Resolves #N` (only fires when the PR base is the upstream repo)

The artifact can be a commit message, PR title, PR body, comment, or issue
body in any repo GitHub indexes. A fork's `parent` metadata is permanent and
public, so anything pushed to `WolffM/markitdown` is eligible to fire a
cross-ref against `microsoft/markitdown` if it contains any of the three
patterns above.

Bare `#N` in a commit on a fork links to the fork's own issues, not the
parent's. That's not a leak vector for our use case.

## The leak vectors we're closing

From jade-hare:

1. **markitdown#183**: a `WolffM/markitdown/pull/9` PR appeared on the
   upstream issue's cross-reference list. The leak was a `#183` reference
   that survived the existing `_sanitize_upstream_refs` because it ran only
   on text the operator authored, not Copilot's output.
2. **mermaid#4099**: a Copilot-authored fork PR titled `"Document Mermaid PR
   #7511 intent and its mapping to issue #4099"`. Copilot wrote the upstream
   issue number directly into a public PR title because it was given the
   number in its assignment context.
3. **hoppscotch#3331**: a Copilot-authored PR with no visible ref in the
   title. The leak is in the body or commit messages — Copilot output the
   existing sanitizer never inspected.

The pattern is the same in all three: the agent **was given** the upstream
identifier, and at some point it echoed it back into a public artifact on a
fork that was structurally linked to upstream.

## The fix: input-context scrubbing

```
                  ┌──────────────────────────────────┐
                  │  hadoku-aggregator                │
                  │  /recon/{slug}/issue-brief/{id}   │
                  │  → contains real upstream URL,    │
                  │    slug, issue number             │
                  └──────────────┬───────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────┐
                  │  scrub_brief()                    │
                  │  - strip full URLs                │
                  │  - strip owner/repo#N refs        │
                  │  - replace upstream slug with     │
                  │    "the upstream project"         │
                  │  - replace #N + URL contexts      │
                  │    with neutral placeholders      │
                  │  - record scrub report            │
                  └──────────────┬───────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │                                      │
              ▼                                      ▼
    ┌─────────────────────┐            ┌──────────────────────────┐
    │ input_context_clean │            │  scrubbed_brief.md       │
    │  gate scans the     │──fail──▶   │  → handed to Copilot     │
    │  scrubbed brief     │            │     as the assignment    │
    │  for any surviving  │            │     context              │
    │  upstream ref       │            └──────────────────────────┘
    └─────────────────────┘                         │
                                                    │ Copilot fixes the
                                                    │ bug, makes commits
                                                    ▼
                                  ┌──────────────────────────────┐
                                  │  WolffM/{repo}                │
                                  │  branch: clean-name           │
                                  │  agent commits live here      │
                                  └──────────────┬───────────────┘
                                                 │ all gates pass
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │  Output sanitizer             │
                                  │  - scan PR title              │
                                  │  - scan PR body               │
                                  │  - scan all commit messages   │
                                  │  - block submission if any    │
                                  │    REAL upstream ref found    │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                       upstream PR opened
                                       against upstream/repo
```

## What gets scrubbed from the brief

The scrubber operates on the JSON returned by
`/recon/{slug}/issue-brief/{id}`. The brief has known structured fields plus
free-form text in the issue body and comments. We scrub all of them.

### Stripped patterns

| Pattern | Example before | Example after |
|---|---|---|
| Full GitHub issue/PR URL | `https://github.com/microsoft/markitdown/issues/183` | `the upstream issue` |
| Slash short ref | `microsoft/markitdown#183` | `the upstream issue` |
| Bare upstream slug | `microsoft/markitdown` | `the upstream project` |
| Issue number alone in identifying contexts | `issue #183`, `PR #7511` | `the issue`, `a related PR` |
| Auto-close keywords | `Fixes #183`, `Closes microsoft/markitdown#183` | (removed entirely) |

### What we keep

- The issue title, body, and comment text — with the substitutions above
- Code snippets, stack traces, repro steps
- Author names that aren't part of refs
- The repo's structure metadata (we tell the agent "you are working in
  markitdown" because it has to know the project name to fix it)

The agent knows it's working on `markitdown`. It does not know the issue is
`#183`.

### What survives in the codebase itself

The repo's source code may contain comments referencing past issues
(`# fix for #99`). We do not scrub the codebase. Those references are bare
`#N` form, which links to fork-local issues (not the parent's), so they're
not a cross-ref vector.

The repo's commit history may contain `Fixes microsoft/markitdown#N` from
prior contributors. The agent might read `git log` while exploring. This is
the residual risk that motivates the **output sanitizer** as a second layer
(below).

## Defense in depth: output sanitizer at submission

Input scrubbing is the primary control. The output sanitizer is a second
layer that runs at the `submittable → submitted` transition.

```python
def submit_upstream_pr(issue, evidence):
    pr_title = evidence.read_text("09-submittable/pr_title.txt")
    pr_body  = evidence.read_text("09-submittable/pr_body.md")
    commits  = evidence.read_json("05-fixed/commit_shas.txt")

    upstream = issue.upstream_slug
    issue_num = issue.upstream_number

    leaks = []
    leaks += scan_for_url(pr_title + pr_body, upstream)
    leaks += scan_for_short_ref(pr_title + pr_body, upstream)
    leaks += scan_for_keyword_ref(pr_body, issue_num)
    leaks += scan_commit_messages(commits, upstream, issue_num)

    if leaks:
        raise SanitizerError(f"output leaks: {leaks}")

    # Open upstream PR. The Fixes #N keyword IS allowed here because
    # this is the only artifact that's intentionally targeted at upstream.
    open_pr(upstream, pr_title, pr_body, base="main")
```

The scanner only flags refs to the *real* upstream slug + issue number
captured at workflow start. Hallucinated refs (`#7511` against a non-existent
upstream PR) are tolerated — they fire no cross-references because there's
nothing to link to.

## Why this kills the leak class

| Leak vector | How input scrubbing prevents it |
|---|---|
| Copilot's PR title contains a real `#N` | Copilot was never told the real `N` — input was scrubbed |
| Copilot's commit message contains the upstream issue URL | Copilot was never given the URL |
| Copilot uses an auto-close keyword targeting upstream | Copilot doesn't know the upstream identity |
| Copilot pattern-completes an `#N` from training data | If the number is hallucinated and doesn't match a real upstream issue, no cross-ref fires; if by chance it matches, the output sanitizer catches the *real-ref* form before submission |
| The fork branch name leaks the issue number | Branch names are operator-controlled, not Copilot-controlled |
| Code/git-log in the cloned repo references upstream | Output sanitizer catches it at submission time |

## What this model does NOT defend against

Be honest about the residual risk:

- **Commit-history poisoning**: if the agent runs `git log` and copies a
  prior `Fixes microsoft/markitdown#42` line into its own commit message,
  the output sanitizer must catch it. Coverage of that scenario depends
  entirely on the scanner's positive-case test fixtures.
- **Tool-output echoing**: if the agent runs `gh pr view` or any GitHub-aware
  tool and pastes the output into a commit, that output may contain real
  refs. The output sanitizer must catch it.
- **Non-English variants**: `修复 #183` or other localized auto-close
  keywords. The scanner's regex set must include the localized forms or
  declare them out of scope.

The output sanitizer is therefore not optional — input scrubbing alone is
not sufficient. Both layers ship in Phase 1.

## Token strategy

No new PAT. The pipeline uses the existing `gh` user token (and `SAML_ORG_TOKEN`
for SAML-protected upstreams via the existing routing in
`services/github_api.py`). All work happens in `WolffM/{repo}` forks the
operator already controls.

## Public fork lifecycle

`WolffM/{repo}` is created on-demand the first time we work on an issue for
a given upstream repo (`gh repo fork upstream/repo`). If it already exists,
we just push to it. Branches are descriptive and operator-readable
(`fix-blank-cells-xlsx`) — no need for hashes since there's no quarantine
boundary to obscure. We never delete `WolffM/{repo}` repos — they accumulate
as the public record.

## Migration

Phase 0 cleaned the namespace by deleting all `WolffM/*` jade-hare-era forks
(a one-time manual cleanup, since removed). Crimson-kitty started with a clean
namespace and re-forks fresh on first issue per upstream. Forks now persist
indefinitely — the fork step reuses any existing fork, so re-dispatch never
re-forks.
