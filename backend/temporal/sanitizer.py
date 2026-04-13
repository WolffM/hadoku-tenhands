"""Commit-rewriter sanitizer pipeline.

Broadens the existing backend.services.oss_firewall._sanitize_upstream_refs
to operate on git history (commit messages, author info), not just the
final PR body. Runs at the `submittable` state transition, before the
clean branch is pushed to the public WolffM/{repo} fork.

Catches:
- URLs to upstream issues in commit messages (markitdown class)
- Short refs `owner/repo#N` in commit messages
- Keyword refs `Fixes #N`, `Closes #N` (allowed only in the final PR body
  via render_pr_body, never in commits)
- Author identity that links back to Copilot (we re-author as WolffM)

See docs/crimson-kitty/quarantine.md for the full pipeline.

Reuses:
    backend.services.oss_firewall._sanitize_upstream_refs (the regex set)
    backend.services.github_api.run_gh_command
    git filter-branch via subprocess

Not yet implemented. Pseudocode:

    def materialize_to_public_fork(issue, evidence) -> str:
        '''Returns the public branch name pushed to WolffM/{repo}.'''
        quarantine_url = evidence.read_text("02-forked/quarantine_url")
        qbranch        = evidence.read_text("02-forked/branch_name")
        upstream       = issue.upstream_slug
        issue_num      = issue.upstream_number

        with temp_clone(quarantine_url) as repo:
            repo.checkout(qbranch)

            # 1. Rewrite every commit message via filter-branch.
            repo.git("filter-branch", "--msg-filter",
                     _msg_sanitize_filter(upstream, issue_num))

            # 2. Re-author as WolffM, drop Copilot identity.
            repo.git("filter-branch", "-f", "--env-filter",
                     _reauthor_filter("WolffM"))

            # 3. Optionally squash to a single commit.
            if should_squash(repo, evidence):
                repo.git("rebase", "-i", "base", "--autosquash")

            # 4. Defense in depth: scan the rewritten history.
            for sha in repo.git("rev-list", "HEAD").splitlines():
                msg = repo.git("show", "--no-patch", "--format=%B", sha)
                if has_upstream_ref(msg, upstream, issue_num):
                    raise SanitizerError(
                        f"upstream ref survived rewrite in commit {sha}"
                    )

            # 5. Push to public fork under a clean, descriptive name.
            public_branch = generate_clean_branch_name(issue, evidence)
            repo.add_remote("public",
                            f"git@github.com:WolffM/{upstream.split('/')[1]}.git")
            repo.git("push", "public", f"HEAD:{public_branch}",
                     "--force-with-lease")

        return public_branch
"""
