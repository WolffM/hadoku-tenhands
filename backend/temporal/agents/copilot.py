"""CopilotAgent — wraps GitHub Copilot SWE assignment + polling.

Implements the `Agent` protocol against GitHub Copilot's coding agent.
The legacy pipeline does this work across `routes/oss_routes_stage3.py`
(assignment) and `services/dispatchers.py::CopilotSWEDispatcher` (polling
+ harvest). This module collapses both into a single Agent surface.

Phase 1B.4.

Constraints from the legacy code we have to honor:
  - GitHub returns HTTP 200 on assignment but silently drops unknown
    assignees. We MUST re-fetch the issue and verify Copilot is actually
    in the assignees list before reporting success.
  - Copilot's PR is correlated to the source issue via an `<issue_title>`
    tag we inject into the assignment context. Match by tag, not by guess.
  - Cross-reference timeline correlation is a fallback only — it leaks
    upstream refs in the legacy pipeline and we don't want to rely on it.
  - Copilot creates a draft PR and never undrafts. Detect "done" via the
    `copilot` check-run status, with a 2+ commits fallback.

The agent itself owns no global state — `gh` calls go through the
existing `services/github_api.py::run_gh_command` wrapper which handles
SAML token routing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from . import (
    Agent,
    AgentJob,
    AgentResult,
    AgentStatus,
    ExitReason,
    IssueRef,
)


COPILOT_ASSIGNEE = "copilot-swe-agent[bot]"
COPILOT_CHECK_RUN_NAME = "copilot"


# Keeping the gh-command call seam parameterized so tests can monkeypatch
# it without importing services. The default lazily imports the existing
# wrapper so we get SAML routing + cache + everything else for free.

def _default_run_gh(args: list[str], stdin_data: str | None = None) -> dict:
    from services.github_api import run_gh_command  # type: ignore
    return run_gh_command(args, stdin_data=stdin_data)


@dataclass
class CopilotAgent:
    """Production Copilot SWE agent adapter.

    Construct with `run_gh=lambda args, stdin_data=None: ...` to inject a
    fake gh runner for tests.
    """

    run_gh: callable = None  # type: ignore[assignment]
    assign_max_attempts: int = 2
    assign_retry_delay_s: float = 3.0

    def __post_init__(self) -> None:
        if self.run_gh is None:
            self.run_gh = _default_run_gh

    # ── assign ────────────────────────────────────────────────────────────

    def assign(
        self,
        issue: IssueRef,
        brief: str,
        instruction: str = "",
    ) -> AgentJob:
        """Create a context issue on the fork, assign Copilot, verify it stuck.

        Returns an `AgentJob` whose `job_id` is the fork issue number (string).
        Raises `RuntimeError` only on programming errors / unexpected gh
        failures. Soft failures (Copilot not available, GitHub silently
        dropped the assignee) raise too — the orchestrator activity will
        translate the exception into a workflow gate failure.

        Idempotent: if there's already an open fork issue with our
        `<issue_title>{title}</issue_title>` tag in its body, adopt
        that assignment instead of creating a duplicate. This lets a
        re-dispatch after an infrastructure-caused abort reuse the
        Copilot work already in flight on the fork rather than burning
        another premium request for a duplicate PR.
        """
        owner, repo = issue.fork_slug.split("/", 1)

        # 1. Build the context issue body. The brief is already scrubbed of
        #    upstream refs by `sanitizer.scrub_brief()` upstream of this call,
        #    so we just inject it verbatim with the correlation tag.
        body = self._build_issue_body(issue, brief, instruction)
        title = self._derive_title(brief)

        existing = self._find_existing_assignment(owner, repo, title)
        if existing is not None:
            return AgentJob(
                job_id=str(existing),
                agent_kind="copilot",
                fork_slug=issue.fork_slug,
                branch_name="",
                metadata={
                    "issue_title": title,
                    "upstream_slug": issue.upstream_slug,
                    "upstream_number": issue.number,
                    "adopted": True,
                },
            )

        # 2. Create the context issue.
        create_payload = json.dumps({
            "title": title,
            "body": body,
            # The <issue_title> tag is what we use later in poll() to
            # correlate Copilot's PR back to this issue.
        })
        create = self.run_gh(
            [
                "api", f"repos/{owner}/{repo}/issues",
                "-X", "POST", "--input", "-",
            ],
            stdin_data=create_payload,
        )
        if not create.get("success"):
            raise RuntimeError(
                f"failed to create fork issue: {create.get('error') or create.get('output', '')[:200]}"
            )
        try:
            created = json.loads(create["output"])
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"create issue returned non-JSON: {e}") from e
        fork_issue_number = str(created["number"])

        # 3. Assign Copilot, retrying once because GitHub's assignee API
        #    sometimes lags right after issue creation.
        assign_payload = json.dumps({"assignees": [COPILOT_ASSIGNEE]})
        assigned = False
        for attempt in range(self.assign_max_attempts):
            if attempt > 0:
                time.sleep(self.assign_retry_delay_s)

            assign_call = self.run_gh(
                [
                    "api",
                    f"repos/{owner}/{repo}/issues/{fork_issue_number}/assignees",
                    "-X", "POST", "--input", "-",
                ],
                stdin_data=assign_payload,
            )
            if not assign_call.get("success"):
                continue

            # GitHub silently drops unknown assignees — verify by re-fetching.
            verify = self.run_gh([
                "api", f"repos/{owner}/{repo}/issues/{fork_issue_number}",
                "--jq", "[.assignees[].login]",
            ])
            if verify.get("success"):
                try:
                    assignees = json.loads(verify["output"].strip())
                    if any("copilot" in a.lower() for a in assignees):
                        assigned = True
                        break
                except (ValueError, TypeError):
                    pass

        if not assigned:
            raise RuntimeError(
                f"GitHub accepted the assignee POST but Copilot was not "
                f"added to {issue.fork_slug}#{fork_issue_number} after "
                f"{self.assign_max_attempts} attempts. Copilot may not be "
                f"available for this repo."
            )

        return AgentJob(
            job_id=fork_issue_number,
            agent_kind="copilot",
            fork_slug=issue.fork_slug,
            branch_name="",  # Copilot picks the branch later; populated in poll()
            metadata={
                "issue_title": title,
                "upstream_slug": issue.upstream_slug,
                "upstream_number": issue.number,
            },
        )

    # ── poll ──────────────────────────────────────────────────────────────

    def poll(self, job: AgentJob) -> AgentStatus:
        """Check whether Copilot has produced a PR + finished its run."""
        if job.agent_kind != "copilot":
            raise ValueError(f"CopilotAgent cannot poll {job.agent_kind!r} job")

        owner, repo = job.fork_slug.split("/", 1)
        issue_title = job.metadata.get("issue_title", "")

        prs = self._list_open_prs(owner, repo)
        copilot_prs = [p for p in prs if "copilot" in (p.get("author", {}).get("login", "")).lower()]
        if not copilot_prs:
            return AgentStatus(state="queued", progress=0.0, last_event="waiting for Copilot PR")

        agent_pr = self._correlate_pr(owner, repo, job.job_id, issue_title, copilot_prs)
        if not agent_pr:
            return AgentStatus(
                state="queued", progress=0.05,
                last_event=f"{len(copilot_prs)} Copilot PR(s) on fork; waiting for correlation",
            )

        pr_number = agent_pr["number"]
        commit_count = len(agent_pr.get("commits", []))
        check_status = self._fetch_check_status(owner, repo, pr_number)

        if check_status == "completed":
            return AgentStatus(
                state="done", progress=1.0,
                last_event=f"copilot check completed on PR #{pr_number}",
            )
        if commit_count >= 2:
            # Fallback: the `copilot` check-run is sometimes missing entirely.
            # 2+ commits means at least one impl commit beyond the "Initial plan".
            return AgentStatus(
                state="done", progress=1.0,
                last_event=f"PR #{pr_number} has {commit_count} commits (check-run absent)",
            )
        return AgentStatus(
            state="running",
            progress=min(0.9, commit_count / 4),
            last_event=f"PR #{pr_number} in progress ({commit_count} commits)",
        )

    # ── harvest ───────────────────────────────────────────────────────────

    def harvest(self, job: AgentJob) -> AgentResult:
        """Collect the agent's PR metadata + diff + commits."""
        if job.agent_kind != "copilot":
            raise ValueError(f"CopilotAgent cannot harvest {job.agent_kind!r} job")

        owner, repo = job.fork_slug.split("/", 1)
        issue_title = job.metadata.get("issue_title", "")

        prs = self._list_open_prs(owner, repo)
        copilot_prs = [p for p in prs if "copilot" in (p.get("author", {}).get("login", "")).lower()]
        agent_pr = self._correlate_pr(owner, repo, job.job_id, issue_title, copilot_prs)
        if not agent_pr:
            return AgentResult(
                commit_shas=[],
                diff_text="",
                files_touched=[],
                agent_log="harvest failed: could not find Copilot PR for this issue",
                exit_reason="error",
            )

        pr_number = agent_pr["number"]
        pr_branch = agent_pr.get("headRefName", "")
        commit_shas = [c.get("sha", "") for c in agent_pr.get("commits", [])]

        # Diff
        diff_call = self.run_gh([
            "pr", "diff", str(pr_number), "-R", f"{owner}/{repo}",
        ])
        diff_text = diff_call.get("output", "") if diff_call.get("success") else ""

        # Files touched
        files_call = self.run_gh([
            "api", f"repos/{owner}/{repo}/pulls/{pr_number}/files",
            "--jq", "[.[].filename]",
        ])
        files_touched: list[str] = []
        if files_call.get("success"):
            try:
                files_touched = json.loads(files_call["output"].strip())
            except (ValueError, TypeError):
                files_touched = []

        # Agent log: Copilot session log if available, else a placeholder
        log_call = self.run_gh([
            "api", f"repos/{owner}/{repo}/pulls/{pr_number}",
            "--jq", ".body",
        ])
        agent_log = log_call.get("output", "").strip() if log_call.get("success") else ""

        exit_reason: ExitReason = "success" if (commit_shas and diff_text.strip()) else "no_changes"

        return AgentResult(
            commit_shas=commit_shas,
            diff_text=diff_text,
            files_touched=files_touched,
            agent_log=agent_log,
            exit_reason=exit_reason,
            pr_url=f"https://github.com/{owner}/{repo}/pull/{pr_number}",
        )

    # ── helpers ───────────────────────────────────────────────────────────

    def _build_issue_body(self, issue: IssueRef, brief: str, instruction: str) -> str:
        """Build the fork issue body Copilot will read.

        The brief is ALREADY scrubbed of upstream refs by the time it gets
        here — we just glue it together with the correlation tag and the
        operator instruction (if any).
        """
        title = self._derive_title(brief)
        parts = [
            f"<issue_title>{title}</issue_title>",
            "",
            "## Context",
            "",
            brief,
        ]
        if instruction:
            parts.extend(["", "## Operator instruction", "", instruction])
        return "\n".join(parts)

    def _derive_title(self, brief: str) -> str:
        """Pull a one-line title out of the brief (first non-empty line, capped)."""
        for line in (brief or "").splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:80]
        return "Crimson-kitty: scrubbed task"

    def _find_existing_assignment(
        self, owner: str, repo: str, title: str,
    ) -> int | None:
        """Return the fork issue number of a prior assignment for this title,
        or None if none exists.

        Matches on the `<issue_title>{title}</issue_title>` marker we embed
        in every context issue body. Only adopts OPEN issues with Copilot
        still in the assignees list — closed or unassigned fork issues mean
        the prior session was either completed (submit stage) or manually
        cleared, and we should start fresh.
        """
        tag = f"<issue_title>{title}</issue_title>"
        listing = self.run_gh([
            "api",
            f"repos/{owner}/{repo}/issues?state=open&assignee={COPILOT_ASSIGNEE}&per_page=30",
            "--jq",
            "[.[] | select(.pull_request == null) | {number, body}]",
        ])
        if not listing.get("success"):
            return None
        try:
            items = json.loads(listing.get("output") or "[]")
        except json.JSONDecodeError:
            return None
        for item in items:
            if tag in (item.get("body") or ""):
                return int(item["number"])
        return None

    def _list_open_prs(self, owner: str, repo: str) -> list[dict]:
        result = self.run_gh([
            "api",
            f"repos/{owner}/{repo}/pulls?state=open&per_page=100",
            "--jq",
            '[.[] | {number: .number, title: .title, body: .body, '
            'headRefName: .head.ref, author: {login: .user.login}}]',
        ])
        if not result.get("success"):
            return []
        try:
            prs = json.loads(result["output"])
        except (ValueError, TypeError):
            return []

        # Enrich with commit SHAs (REST list doesn't include commits inline)
        for pr in prs:
            commits_call = self.run_gh([
                "api",
                f"repos/{owner}/{repo}/pulls/{pr['number']}/commits?per_page=100",
                "--jq", "[.[].sha]",
            ])
            if commits_call.get("success"):
                try:
                    pr["commits"] = [{"sha": s} for s in json.loads(commits_call["output"])]
                except (ValueError, TypeError):
                    pr["commits"] = []
            else:
                pr["commits"] = []
        return prs

    def _correlate_pr(
        self,
        owner: str,
        repo: str,
        fork_issue_number: str,
        issue_title: str,
        candidate_prs: list[dict],
    ) -> dict | None:
        """Find the Copilot PR that corresponds to this fork issue.

        Strategy: match by the `<issue_title>` tag we injected into the
        issue body. Copilot copies the body verbatim into the PR.
        Falls back to "single available PR" if there's only one and the
        tag match fails.
        """
        if not candidate_prs:
            return None

        if issue_title:
            tag = f"<issue_title>{issue_title}</issue_title>"
            tagged = [p for p in candidate_prs if tag in (p.get("body") or "")]
            if tagged:
                # Most commits wins (in case of duplicates from retries)
                return max(tagged, key=lambda p: len(p.get("commits", [])))

        if len(candidate_prs) == 1:
            return candidate_prs[0]

        return None

    def _fetch_check_status(self, owner: str, repo: str, pr_number: int) -> str | None:
        head_call = self.run_gh([
            "pr", "view", str(pr_number), "-R", f"{owner}/{repo}",
            "--json", "headRefOid", "--jq", ".headRefOid",
        ])
        if not head_call.get("success"):
            return None
        head_sha = head_call["output"].strip()

        check_call = self.run_gh([
            "api",
            f"repos/{owner}/{repo}/commits/{head_sha}/check-runs",
            "--jq",
            f'.check_runs[] | select(.name=="{COPILOT_CHECK_RUN_NAME}") | .status',
        ])
        if not check_call.get("success"):
            return None
        return check_call["output"].strip() or None


# Type-check that CopilotAgent satisfies the Agent protocol.
_check: Agent = CopilotAgent()  # noqa: F841
