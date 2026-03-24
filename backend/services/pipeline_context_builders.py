"""Pipeline context builders — build review and remediation prompts.

Module-level functions that assemble context strings for the review and
remediation agents. All content is sanitized to prevent upstream cross-linking.
"""

import logging

try:
    from services.github_api import run_gh_command
    from services.oss_service import _sanitize_upstream_refs
    from helpers.oss_helpers import strip_leading_header
except ImportError:
    from .github_api import run_gh_command
    from .oss_service import _sanitize_upstream_refs
    from ..helpers.oss_helpers import strip_leading_header

logger = logging.getLogger(__name__)


def build_remediation_context(assignment, ctx, get_sa_findings_fn):
    """Build remediation prompt from review comments + SA findings.

    Args:
        assignment: Assignment dict.
        ctx: Runtime context dict with my_user, repo, etc.
        get_sa_findings_fn: Callable(assignment, ctx) -> str returning SA findings.
    """
    parts = ["## Remediation Required\n"]

    pr_number = assignment.get("stage4_pr_number")
    my_user = ctx["my_user"]
    repo = ctx["repo"]

    # Gather inline review comments
    if pr_number:
        result = run_gh_command([
            "api",
            f"repos/{my_user}/{repo}/pulls/{pr_number}/comments",
            "--jq",
            '.[] | "- `\\(.path):\\(.line // .original_line // \"?\")`: \\(.body)"',
        ])
        if result["success"] and result["output"].strip():
            parts.append(
                "### Review Comments\n"
                f"{result['output'].strip()}\n"
            )

    # Gather SA findings that survived auto-fix
    findings = get_sa_findings_fn(assignment, ctx)
    if findings:
        parts.append(
            "### Static Analysis Findings (post auto-fix)\n"
            f"```\n{findings}\n```\n"
        )

    parts.append(
        "### Instructions\n"
        "1. Address each review comment above.\n"
        "2. Fix any remaining static analysis findings.\n"
        "3. Do not introduce new issues.\n"
    )

    context = "\n".join(parts)
    context = _sanitize_upstream_refs(context)
    return context


def build_review_context(assignment, ctx, svc, get_sa_findings_fn):
    """Build review context from dossier + static analysis findings.

    This assembles the information the review agent needs to do a
    repo-specific review. All content is sanitized to prevent
    upstream cross-linking.

    Args:
        assignment: Assignment dict.
        ctx: Runtime context dict with my_user, repo, etc.
        svc: OSSService instance (may be None).
        get_sa_findings_fn: Callable(assignment, ctx) -> str returning SA findings.
    """
    if not svc:
        return ""

    parts = ["## Review Context\n"]

    # Get dossier for contribution rules and patterns
    origin_slug = assignment.get("origin_slug", "")
    if origin_slug:
        hyphenated = origin_slug.replace("/", "-")
        dossier_data = svc.get_dossier(hyphenated)
        if dossier_data and dossier_data.get("sections"):
            sections = dossier_data["sections"]
            if sections.get("contributionRules"):
                parts.append(
                    "### Contribution Rules\n"
                    f"{strip_leading_header(sections['contributionRules'])}\n"
                )
            if sections.get("successPatterns"):
                parts.append(
                    "### What Successful PRs Look Like\n"
                    f"{strip_leading_header(sections['successPatterns'])}\n"
                )
            if sections.get("antiPatterns"):
                parts.append(
                    "### Common Rejection Reasons\n"
                    f"{strip_leading_header(sections['antiPatterns'])}\n"
                )

    # Get static analysis findings
    findings = get_sa_findings_fn(assignment, ctx)
    if findings:
        parts.append(
            "### Static Analysis Findings\n"
            f"```\n{findings}\n```\n"
        )

    parts.append(
        "### Review Instructions\n"
        "1. Check that the code change fixes the problem.\n"
        "2. Check for issues flagged by static analysis above.\n"
        "3. Verify the change follows contribution rules and patterns.\n"
        "4. Check for anti-patterns that would cause upstream rejection.\n"
        "5. Leave specific, actionable review comments.\n"
    )

    context = "\n".join(parts)

    # Sanitize to prevent upstream cross-linking
    context = _sanitize_upstream_refs(context)
    return context
