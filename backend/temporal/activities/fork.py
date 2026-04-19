"""Fork + scrub-brief activity — Phase 1C.2.

Ensures `WolffM/{repo}` exists as a fork of upstream, creates a fresh
working branch, and writes a sanitized brief into evidence at
`02-forked/scrubbed_brief.md` for the agent to read. The
`input_context_clean` gate runs after this and verifies zero real refs
survived.

Also configures fork-level safety settings after the fork exists:
disables inherited upstream CI workflows so Copilot's pushes don't
trigger the upstream's full matrix build (which burns through our
Actions budget on large repos like jest, vscode, react).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..sanitizer import scrub_brief

logger = logging.getLogger(__name__)

# Fork provisioning on GitHub is async — `gh repo fork` returns before
# the fork's repo-level API endpoints (especially /actions/permissions)
# are serving. Retry critical steps with exponential backoff before
# giving up. If these still fail, the workflow raises and aborts cleanly
# rather than proceeding with an unlocked fork.
_FORK_RETRIES = 5
_FORK_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 16.0)

# Only this workflow stays enabled on the fork. Everything else —
# inherited from upstream or auto-provisioned by GitHub (Dependabot,
# CodeQL, Copilot PR reviewer, etc.) — gets disabled. The single kept
# entry is the Copilot coding agent itself, which is how Copilot
# actually produces PRs (its runtime is billed as Copilot premium
# requests, not Actions minutes, so it doesn't eat the Actions budget).
#
# Adding a pattern here means paying for every Copilot push to every
# fork forever, so keep it tight.
_KEEP_WORKFLOW_PATHS = {
    "dynamic/copilot-swe-agent/copilot",
}


def _default_run_gh(args: list[str], stdin_data: str | None = None) -> dict:
    from services.github_api import run_gh_command  # type: ignore
    return run_gh_command(args, stdin_data=stdin_data)


def _gh_with_retry(
    run_gh,
    args: list[str],
    *,
    stdin_data: str | None = None,
    label: str,
    retries: int = _FORK_RETRIES,
) -> dict:
    """Call gh with bounded exponential backoff, returning the final result.

    GitHub's fork provisioning is async — right after `gh repo fork`
    returns, repo-level endpoints can 404 or 422 for several seconds.
    Callers that hit those endpoints during fork setup must retry; this
    helper centralizes the backoff so the call sites stay readable.
    """
    last = {"success": False, "error": "never attempted"}
    for attempt in range(retries):
        result = run_gh(args, stdin_data=stdin_data) if stdin_data is not None else run_gh(args)
        if result.get("success"):
            if attempt:
                logger.info("%s succeeded on attempt %d/%d", label, attempt + 1, retries)
            return result
        last = result
        err = (result.get("error") or "")[:160]
        logger.info("%s attempt %d/%d failed (%s); sleeping", label, attempt + 1, retries, err)
        if attempt + 1 < retries:
            time.sleep(_FORK_RETRY_DELAYS[min(attempt, len(_FORK_RETRY_DELAYS) - 1)])
    return last


def _configure_fork_safety(fork_slug: str, run_gh) -> dict:
    """Lock down the fork so Copilot pushes don't trigger upstream CI.

    Runs after the fork exists (whether we just created it or it was
    already there). Critical steps (enable issues, set Actions policy)
    retry with exponential backoff to tolerate GitHub's async fork
    provisioning. Raises RuntimeError if either of those still fails
    after retries — better to abort the workflow cleanly than to hand
    an unlocked fork to Copilot.

    Disabling inherited workflows is best-effort (logged, not raised).

    Returns a summary dict the caller can include in evidence.
    """
    owner, repo = fork_slug.split("/", 1)
    summary = {
        "issues_enabled": False,
        "actions_policy_set": False,
        "disabled_workflows": 0,
        "kept_workflows": [],
    }

    # 1. Enable Issues. Forks inherit has_issues=false from GitHub by
    #    default, which blocks CopilotAgent.assign() from creating the
    #    context issue it needs to hand off to Copilot.
    issues = _gh_with_retry(
        run_gh,
        ["api", f"repos/{fork_slug}", "-X", "PATCH", "-f", "has_issues=true"],
        label=f"enable has_issues on {fork_slug}",
    )
    summary["issues_enabled"] = bool(issues.get("success"))
    if not issues.get("success"):
        raise RuntimeError(
            f"failed to enable issues on {fork_slug} after {_FORK_RETRIES} attempts: "
            f"{issues.get('error') or issues.get('output', '')[:200]}"
        )

    # 2. Enable Actions with a permissive policy. We need the Copilot
    #    coding agent workflow to run; disabling at the repo level would
    #    block that too. This is the endpoint that races hardest against
    #    fork provisioning — retries are load-bearing.
    policy = _gh_with_retry(
        run_gh,
        ["api", f"repos/{fork_slug}/actions/permissions",
         "-X", "PUT", "-f", "enabled=true", "-f", "allowed_actions=all"],
        label=f"set Actions policy on {fork_slug}",
    )
    summary["actions_policy_set"] = bool(policy.get("success"))
    if not policy.get("success"):
        raise RuntimeError(
            f"failed to set Actions policy on {fork_slug} after {_FORK_RETRIES} attempts: "
            f"{policy.get('error') or policy.get('output', '')[:200]}"
        )

    # 2. Disable every inherited workflow except the ones we whitelist.
    listing = run_gh([
        "api", f"repos/{fork_slug}/actions/workflows",
        "--jq", ".workflows[] | [.id, .path, .state] | @tsv",
        "--paginate",
    ])
    if not listing.get("success"):
        logger.warning("could not list workflows on %s; skipping disable step", fork_slug)
        return summary

    for line in (listing.get("output") or "").strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        wf_id, wf_path, wf_state = parts[0], parts[1], parts[2]

        if wf_path in _KEEP_WORKFLOW_PATHS:
            summary["kept_workflows"].append(wf_path)
            continue

        if wf_state == "active":
            r = run_gh([
                "api", f"repos/{fork_slug}/actions/workflows/{wf_id}/disable",
                "-X", "PUT",
            ])
            if r.get("success"):
                summary["disabled_workflows"] += 1

    if summary["disabled_workflows"]:
        logger.info("disabled %d inherited workflows on %s (kept %d)",
                    summary["disabled_workflows"], fork_slug, len(summary["kept_workflows"]))
    return summary


def fork_and_scrub_brief(
    upstream_slug: str,
    issue_number: int,
    raw_brief_text: str,
    branch_name: str,
    evidence,
    *,
    fork_owner: str = "WolffM",
    run_gh=None,
) -> dict:
    """Ensure fork exists + create branch + scrub brief into evidence.

    Idempotent on the fork side: if `{fork_owner}/{repo}` already exists,
    we skip the fork call. Branch creation is best-effort — if it already
    exists we just push to it.

    Writes:
      - 02-forked/fork_url
      - 02-forked/branch_name
      - 02-forked/scrubbed_brief.md
      - 02-forked/scrub_report.json
    """
    if run_gh is None:
        run_gh = _default_run_gh

    # If no raw brief was provided in the dispatch payload, fall back to
    # the brief that the eligibility activity already fetched from the
    # aggregator. This is the normal path — the dispatch route rarely has
    # the brief text at dispatch time.
    if not raw_brief_text.strip() and evidence.exists("01-eligible/issue_brief.json"):
        brief_data = evidence.read_json("01-eligible/issue_brief.json")
        raw_brief_text = brief_data.get("brief", "")
        if not raw_brief_text and isinstance(brief_data.get("issue"), dict):
            issue = brief_data["issue"]
            raw_brief_text = f"## {issue.get('title', '')}\n\n{issue.get('body', '')}"

    _, repo = upstream_slug.split("/", 1)
    fork_slug = f"{fork_owner}/{repo}"

    # 1. Ensure fork exists
    fork_check = run_gh(["api", f"repos/{fork_slug}", "--silent", "-i"])
    if not fork_check.get("success"):
        # Doesn't exist — create it
        create = run_gh(["repo", "fork", upstream_slug, "--clone=false", "--default-branch-only"])
        if not create.get("success"):
            raise RuntimeError(
                f"failed to fork {upstream_slug}: {create.get('error') or create.get('output', '')[:200]}"
            )

    # 2. Lock down the fork — disables inherited CI so Copilot pushes
    #    don't trigger upstream's full matrix build on every commit.
    safety_summary = _configure_fork_safety(fork_slug, run_gh)

    # 3. Scrub the brief
    scrubbed, report = scrub_brief(raw_brief_text, upstream_slug, issue_number)

    # 4. Write evidence
    evidence.write_text("02-forked/fork_url", f"https://github.com/{fork_slug}")
    evidence.write_text("02-forked/branch_name", branch_name)
    evidence.write_text("02-forked/scrubbed_brief.md", scrubbed)
    evidence.write_json("02-forked/scrub_report.json", report.to_dict())
    evidence.write_json("02-forked/fork_safety.json", safety_summary)

    return {
        "ok": True,
        "fork_slug": fork_slug,
        "branch_name": branch_name,
        "scrub_count": report.count,
        "workflows_disabled": safety_summary["disabled_workflows"],
    }
