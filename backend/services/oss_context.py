"""
OSSContextMixin — agent context building for fork issues.

Builds the markdown body posted to fork issues that agents (Copilot, etc.)
read as their work instructions. Implements a three-tier context strategy:
brief → dossier → CONTRIBUTING.md.
"""

import json
import base64
import logging

from .github_api import run_gh_command
from .oss_service import _sanitize_upstream_refs, _detect_tool_from_issue

try:
    from ..helpers.oss_helpers import strip_leading_header
    from ..config import CONTRIBUTING_MD_MAX_CHARS
except ImportError:
    from helpers.oss_helpers import strip_leading_header
    from config import CONTRIBUTING_MD_MAX_CHARS

logger = logging.getLogger(__name__)


class OSSContextMixin:
    """Agent context building for the OSS pipeline."""

    def build_agent_context(self, origin_owner, repo, issue_number, issue_title, issue_url,
                             dossier=None, issue_brief=None, return_metadata=False,
                             is_self_owned=False, dossier_completeness=None):
        """Build the markdown context body for a fork issue assigned to an agent.

        Three-tier context strategy:
        1. issue_brief.brief available: Brief-first layout — aggregator's pre-built brief
           (rules, env setup, issue details, contribution rules) at top, our TDD workflow appended.
        2. dossier available (no brief): Our own rules + dossier sections.
        3. Neither available: Our own rules + CONTRIBUTING.md via gh CLI.

        Args:
            return_metadata: If True, return (body, metadata) tuple instead of just body.
            is_self_owned: If True, the repo is owned by the contributor (not a fork).
        """
        metadata = {
            "issue_body_fetched": False,
            "contributing_fetched": False,
            "dossier_used": False,
            "issue_brief_used": False,
            "sources": [],
        }

        # --- Build common elements used by all tiers ---
        if is_self_owned:
            pr_target = f"Your changes will be reviewed as a PR on `{origin_owner}/{repo}`."
        else:
            pr_target = f"Your changes will be submitted as a PR to `{origin_owner}/{repo}`."

        # --- Tier 1: Brief available ---
        if issue_brief and issue_brief.get("brief"):
            brief_issue_body = ""
            if issue_brief.get("issue"):
                brief_issue_body = issue_brief["issue"].get("body") or ""
            detected_tool = _detect_tool_from_issue(brief_issue_body)
            reproduce_step, verify_step = self._build_tdd_steps(detected_tool)

            # TDD workflow FIRST — this is the most important section
            body = self._build_workflow_header(pr_target, reproduce_step, verify_step)
            # Then the brief content (issue details, env setup, contribution rules, etc.)
            body += "\n---\n"
            body += _sanitize_upstream_refs(issue_brief["brief"])

            metadata["issue_brief_used"] = True
            metadata["issue_body_fetched"] = True
            metadata["context_tier"] = 1
            metadata["sources"].append("aggregator-issue-brief")

            if return_metadata:
                return body, metadata
            return body

        # --- Tiers 2 & 3: No brief — build context ourselves ---
        issue_body = ""
        original = run_gh_command([
            "issue", "view", str(issue_number),
            "-R", f"{origin_owner}/{repo}",
            "--json", "body,labels"
        ])
        original_data = {}
        if original["success"]:
            try:
                original_data = json.loads(original["output"])
                metadata["issue_body_fetched"] = True
                metadata["sources"].append("gh-issue-view")
            except (json.JSONDecodeError, KeyError):
                pass
        issue_body = original_data.get('body', '')
        issue_body = _sanitize_upstream_refs(issue_body)

        detected_tool = _detect_tool_from_issue(issue_body)
        reproduce_step, verify_step = self._build_tdd_steps(detected_tool)

        # TDD workflow FIRST, then issue context
        body = self._build_workflow_header(pr_target, reproduce_step, verify_step)
        body += f"""
---
## Issue Context
**Title:** {issue_title}

### Description
{issue_body or '*No description provided.*'}
"""

        # Tier 2: Use dossier sections if available (sanitize to prevent cross-refs)
        _tier2_keys = ("contributionRules", "successPatterns",
                       "environmentSetup", "devEnvironment")
        if dossier and any(dossier.get(k) for k in _tier2_keys):
            if dossier.get("contributionRules"):
                body += f"\n---\n## Contribution Rules\n{strip_leading_header(_sanitize_upstream_refs(dossier['contributionRules']))}\n"
            metadata["dossier_used"] = True
            metadata["context_tier"] = 2
            metadata["sources"].append("aggregator-dossier")
            if dossier_completeness:
                metadata["dossier_completeness"] = dossier_completeness

            if dossier.get("successPatterns"):
                body += f"\n---\n## What Successful PRs Look Like\n{strip_leading_header(_sanitize_upstream_refs(dossier['successPatterns']))}\n"

            # Anti-patterns — only when completeness marks content as real (not boilerplate)
            anti = dossier.get("antiPatterns")
            if anti and isinstance(anti, str):
                has_real_content = (dossier_completeness or {}).get("antiPatterns", False)
                if has_real_content:
                    body += f"\n---\n## Common Rejection Reasons\n{strip_leading_header(_sanitize_upstream_refs(anti))}\n"

            # Environment setup — handle rename from devEnvironment to environmentSetup
            env = dossier.get("environmentSetup") or dossier.get("devEnvironment")
            if env:
                env_text = env if isinstance(env, str) else str(env)
                if env_text.strip():
                    body += f"\n---\n## Environment & Setup\n{strip_leading_header(_sanitize_upstream_refs(env_text))}\n"

        # Tier 3: Fetch CONTRIBUTING.md via gh CLI
        else:
            metadata["context_tier"] = 3
            contrib = run_gh_command([
                "api", f"/repos/{origin_owner}/{repo}/contents/CONTRIBUTING.md",
                "--jq", ".content"
            ])
            if contrib["success"] and contrib["output"].strip():
                try:
                    contrib_text = base64.b64decode(contrib["output"].strip()).decode("utf-8")
                    contrib_text = _sanitize_upstream_refs(contrib_text[:CONTRIBUTING_MD_MAX_CHARS])
                    body += f"\n---\n## CONTRIBUTING.md\n<details><summary>Expand</summary>\n\n{contrib_text}\n\n</details>\n"
                    metadata["contributing_fetched"] = True
                    metadata["sources"].append("gh-contributing-md")
                except Exception as e:
                    logger.warning("Failed to fetch CONTRIBUTING.md for %s/%s: %s", origin_owner, repo, e)

        # Quirk warnings — sourced from health (via issue_brief), applies to all tiers
        quirks = None
        if issue_brief and issue_brief.get("repoHealth"):
            quirks = issue_brief["repoHealth"].get("detectedQuirks")
        if quirks:
            body += "\n---\n## Important Quirks & Warnings\n"
            for quirk in quirks:
                impact = quirk.get("impact", "minor")
                icon = "BLOCKER" if impact == "blocker" else "WARNING" if impact == "important" else "NOTE"
                body += f"**[{icon}]** {quirk.get('type', 'unknown')}: {_sanitize_upstream_refs(quirk.get('description', ''))}\n"
                if quirk.get("evidence"):
                    body += f"  Evidence: {_sanitize_upstream_refs(quirk['evidence'])}\n"
            body += "\n"

        if return_metadata:
            return body, metadata
        return body

    @staticmethod
    def _build_workflow_header(pr_target, reproduce_step, verify_step):
        """Build the mandatory workflow section that goes at the TOP of every context issue."""
        return f"""## Mandatory Workflow (Read First — Do NOT Skip)

{pr_target}

You MUST follow these phases in order. Do NOT skip ahead.

### Phase 1: Reproduce (MUST complete before Phase 2)
{reproduce_step}
- **Do NOT proceed to Phase 2 until you have confirmed a failing test or reproduced the issue.**
- If you cannot reproduce it, document why in a comment on this issue and stop.

### Phase 2: Implement (MUST complete before Phase 3)
2. **Implement the fix:** Make the minimal code change needed to resolve the issue.
   Follow the upstream repo's coding style and conventions. Write clear commit messages.
- Do NOT refactor unrelated code. Do NOT add features beyond what the issue asks for.

### Phase 3: Verify (MUST complete before committing)
{verify_step}
- Re-run the specific failing test from Phase 1 to confirm it now passes.
- Run the full test suite to check for regressions.
- **Do NOT commit until all tests pass.**

### Rules
- **DO NOT** reference, close, or link any external issues in your PR or commits. No "Closes", "Fixes", or "Resolves" directives.
- **DO NOT** use GitHub MCP tools to look up issues on other repositories.
- **DO NOT** modify or weaken a test to make it pass. The test must accurately verify the fix.
- **DO NOT** disable linter rules or add suppression comments to "fix" the issue.
- **DO NOT** commit `__pycache__/` directories. Add to `.gitignore` if missing.
- Keep changes minimal and focused.
- If the repo has a test suite, your PR **must** include a test that covers the fix.

### If You Cannot Complete This Task
If you are unable to reproduce the finding or implement a fix:
- **Add a comment on this issue** explaining what you tried and why it failed.
- Include the relevant tool output or error messages in the comment.
- Do **NOT** create a PR with no meaningful changes or with suppressed warnings.
"""

    @staticmethod
    def _build_tdd_steps(detected_tool):
        """Build TDD reproduce/verify steps based on detected tool.

        Returns (reproduce_step, verify_step) strings.
        """
        if detected_tool:
            reproduce_step = (
                f"1. **Reproduce the finding:** Run `{detected_tool}` on the affected file(s) "
                f"to confirm the issue exists.\n"
                f"   If `{detected_tool}` is not already installed, install it first. "
                f"Capture the output showing the finding."
            )
            verify_step = (
                f"3. **Verify the fix:** Re-run `{detected_tool}` on the affected file(s) "
                f"and confirm the finding is resolved.\n"
                f"   The tool should no longer report this specific issue. "
                f"No new issues should be introduced."
            )
        else:
            reproduce_step = (
                "1. **Reproduce the issue:** Write a failing test or run the relevant "
                "linting/analysis tool to confirm the problem.\n"
                "   If the repo has a test suite, add a test case that fails due to this issue."
            )
            verify_step = (
                "3. **Verify the fix:** Re-run the test or tool and confirm the issue is resolved.\n"
                "   All existing tests must still pass. No new issues should be introduced."
            )
        return reproduce_step, verify_step
