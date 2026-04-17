"""Fork + scrub-brief activity — Phase 1C.2.

Ensures `WolffM/{repo}` exists as a fork of upstream, creates a fresh
working branch, and writes a sanitized brief into evidence at
`02-forked/scrubbed_brief.md` for the agent to read. The
`input_context_clean` gate runs after this and verifies zero real refs
survived.
"""

from __future__ import annotations

import json
from typing import Any

from ..sanitizer import scrub_brief


def _default_run_gh(args: list[str], stdin_data: str | None = None) -> dict:
    from services.github_api import run_gh_command  # type: ignore
    return run_gh_command(args, stdin_data=stdin_data)


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

    # 2. Scrub the brief
    scrubbed, report = scrub_brief(raw_brief_text, upstream_slug, issue_number)

    # 3. Write evidence
    evidence.write_text("02-forked/fork_url", f"https://github.com/{fork_slug}")
    evidence.write_text("02-forked/branch_name", branch_name)
    evidence.write_text("02-forked/scrubbed_brief.md", scrubbed)
    evidence.write_json("02-forked/scrub_report.json", report.to_dict())

    return {
        "ok": True,
        "fork_slug": fork_slug,
        "branch_name": branch_name,
        "scrub_count": report.count,
    }
