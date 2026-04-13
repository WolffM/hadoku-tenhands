# Quarantine model

The single biggest structural fix in crimson-kitty: **the agent never writes
to a public repo**. All Copilot work happens in `WolffM-temporal`, a private
GitHub org that GitHub's cross-reference auto-detection cannot link back to
upstream issues.

This is the "untrust the agent" principle made concrete.

## The leak vectors we're closing

From jade-hare:

1. **markitdown#183**: a `WolffM/markitdown/pull/9` PR appeared on the
   upstream issue's cross-reference list. Source unclear — likely a `#183`
   reference somewhere in the fork PR body that got past the sanitizer.
2. **mermaid#4099**: a Copilot-authored fork PR titled `"Document Mermaid PR
   #7511 intent and its mapping to issue #4099"`. The agent wrote the
   upstream issue number directly into a public PR title.
3. **hoppscotch#3331**: a Copilot-authored PR with no visible ref in the
   title. The leak is in the body or commit messages — content the
   sanitizer doesn't currently inspect.

The pattern: GitHub creates an automatic cross-reference whenever a public
artifact (PR title, PR body, commit message, issue body, comment) contains
either a URL to the upstream issue, an `owner/repo#N` short ref, or a
keyword like `Fixes #N` / `Closes #N`. Once that artifact exists in a public
repo and references the upstream, the cross-reference fires immediately and
appears in the upstream issue's timeline.

Our existing `_sanitize_upstream_refs` only runs on content *we* author. The
agent bypasses it.

## The fix: quarantine org

```
                                    ┌────────────────────────────┐
                                    │   WolffM-temporal (org)    │
                                    │   private, sealed          │
                                    │                            │
  agent assignment ──► fork ──►     │   markitdown-a3f9b1        │
                                    │   ├─ branch: w-7c2e1f      │
                                    │   ├─ Copilot pushes here   │
                                    │   └─ all dirty work        │
                                    │                            │
                                    └─────────────┬──────────────┘
                                                  │ all gates pass
                                                  ▼
                              ┌─────────────────────────────────┐
                              │  Sanitizer + commit rewriter    │
                              │  - rewrites commit messages     │
                              │  - rewrites author              │
                              │  - clean PR title/body          │
                              └─────────────┬───────────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────────────┐
                              │   WolffM/markitdown (public)    │
                              │   - clean branch pushed here    │
                              │   - upstream PR opened from     │
                              │     this branch                 │
                              └─────────────────────────────────┘
                                            │
                                            ▼
                                   microsoft/markitdown
                                       (upstream)
```

## Org configuration

**Org name**: `WolffM-temporal`

**Visibility**: All repos created here are **private**. Org-level setting:
"Members can create private repositories." We never use the public
visibility setting.

**Membership**: Only `WolffM` and a service PAT. No collaborators.

**Repo naming**: `{repo-name}-{short-hash}`. The hash is a 6-char prefix of
`sha1(upstream_slug + issue_number + timestamp)`. Example:
`microsoft/markitdown#183 → markitdown-a3f9b1`. **Never** use the upstream
issue number in the repo name.

**Branch naming**: Inside each quarantine repo, branches are
`w-{6-char-hash}`. Hash is `sha1(branch_purpose + nonce)`. Examples:
`w-7c2e1f`, `w-44d811`. **Never** use issue numbers, descriptive names like
`fix-issue-1234`, or anything Copilot is allowed to choose.

**Repo lifecycle**: Created when issue enters `forked` state. Deleted 30
days after the issue reaches a terminal state (`merged`, `closed_by_upstream`,
`aborted`). Deletion is a Temporal scheduled workflow.

## Token strategy

We need a separate PAT for `WolffM-temporal`:

- **PAT scope**: `repo` (private repos), `delete_repo`, `workflow`. Nothing
  more.
- **Stored as**: `TEMPORAL_QUARANTINE_PAT` in `.env`
- **Used by**: only `services/quarantine_service.py` (new). Activities call
  this service. The PAT never leaves the activity.

Existing tokens (`MSFT_SSO`, the default `gh` token) keep their current
scope. We do not give the quarantine PAT permission to anything in
`WolffM/*` or upstream orgs.

## The sanitizer pipeline (commit rewriting)

When the issue reaches `submittable`, before we push to `WolffM/{repo}`, we
run the sanitizer pipeline. This is the only place clean-up happens — by
this point all gates have passed.

```python
def materialize_to_public_fork(issue, evidence):
    quarantine_url = evidence.read_text("02-forked/quarantine_url")
    qbranch        = evidence.read_text("02-forked/branch_name")
    upstream       = issue.upstream_slug
    issue_num      = issue.upstream_number

    with temp_clone(quarantine_url) as repo:
        repo.checkout(qbranch)

        # 1. Rewrite every commit message.
        repo.git("filter-branch", "--msg-filter", _sanitize_filter(upstream, issue_num))

        # 2. Re-author commits. The fork should look like WolffM, not Copilot.
        repo.git("filter-branch", "-f", "--env-filter", _reauthor_filter("WolffM"))

        # 3. Squash to a single commit if the agent left intermediate noise.
        if should_squash(repo, evidence):
            repo.git("rebase", "-i", "base", "--autosquash")

        # 4. Validate the rewritten history has zero refs (defense in depth).
        for sha in repo.git("rev-list", "HEAD").splitlines():
            msg = repo.git("show", "--no-patch", "--format=%B", sha)
            if has_upstream_ref(msg, upstream, issue_num):
                raise SanitizerError(f"ref survived rewrite in {sha}")

        # 5. Push to public fork under a fresh, descriptive branch name.
        public_branch = generate_clean_branch_name(issue, evidence)
        repo.add_remote("public", f"git@github.com:WolffM/{upstream.split('/')[1]}.git")
        repo.git("push", "public", f"HEAD:{public_branch}", "--force-with-lease")

    return public_branch
```

The public branch name **is** allowed to be descriptive (`fix-blank-cells-xlsx`)
because by this point we've decided to make this PR. But it must not contain
the literal issue number — we encode that only in the PR body's `Fixes #N`
keyword, which is intentional.

## Public fork creation

`WolffM/{repo}` is created on-demand the first time we materialize a
clean branch for a given upstream repo. If it already exists, we just push
to it. We never delete `WolffM/{repo}` repos — they accumulate as our public
record.

## Why this kills the leak class

| Leak vector | How quarantine prevents it |
|---|---|
| Copilot's PR title contains `#N` | The Copilot PR is in `WolffM-temporal`, never indexed against upstream |
| Copilot's commit message contains the upstream issue URL | Same — the commit lives in quarantine until rewritten |
| The fork branch name leaks the issue number | Branch names in quarantine are hashed; public branches are operator-controlled |
| The sanitizer misses a ref | Defense in depth: the `no_upstream_refs` gate runs on the materialized public artifacts before push, and rejects the materialization if a ref slips through |
| Copilot opens its own PR to upstream | Cannot — Copilot's quarantine PAT has no permission on the upstream org |

## Migration concern

The old pipeline's existing `WolffM/{repo}` forks contain history that may
include unsanitized branches. Crimson-kitty does not touch existing forks —
it creates new branches under the same fork. Any old branches that leak
remain a historical record but won't trigger new cross-references unless
modified.

If we want to clean up the historical record, that's a separate one-time
script. Out of scope for crimson-kitty v1.
