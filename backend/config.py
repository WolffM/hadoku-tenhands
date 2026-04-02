"""
VibeDispatch Configuration Constants
"""

import os

# Platform constants - centralize here so they are easy to swap for other platforms
PLATFORM_PREFIX = "github"  # Used in issue ID format: "github-owner-repo-number"
COPILOT_ASSIGNEE = "copilot-swe-agent[bot]"
COPILOT_REVIEWER = "copilot-pull-request-reviewer[bot]"
COPILOT_MENTION = "@copilot"
COPILOT_CHECK_RUN_NAME = "copilot"
GITHUB_NOREPLY_EMAIL_TEMPLATE = "{uid}+{login}@users.noreply.github.com"
GITHUB_ACTIONS_BOT_NAME = "github-actions[bot]"
GITHUB_ACTIONS_BOT_EMAIL = "github-actions[bot]@users.noreply.github.com"

# Branch naming
CLEAN_BRANCH_PREFIX = "fix/"

# Context building limits
CONTRIBUTING_MD_MAX_CHARS = 3000

# VibeCheck source repo — override with VIBECHECK_REPO env var (owner/repo format)
VIBECHECK_REPO = os.environ.get("VIBECHECK_REPO", "WolffM/vibecheck")
VIBECHECK_WORKFLOW_FILE = "vibecheck.yml"
VIBECHECK_WORKFLOW_NAME = "vibeCheck"

# Dispatch guardrails — override via env vars
MAX_REPO_SIZE_KB = int(os.environ.get("MAX_REPO_SIZE_KB", 500_000))
MIN_CORE_REMAINING = int(os.environ.get("MIN_CORE_REMAINING", 200))

# VibeCheck workflow template — uses VIBECHECK_REPO so the action reference
# stays in sync with the env-var override.
_VIBECHECK_WORKFLOW_TEMPLATE = """\
name: vibeCheck
on:
  workflow_dispatch:

permissions:
  contents: write
  issues: write
  pull-requests: write
  security-events: write

jobs:
  analyze:
    name: Static Analysis
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run vibeCheck
        uses: {vibecheck_repo}@main
        with:
          github_token: ${{{{ secrets.GITHUB_TOKEN }}}}
          cadence: weekly
          severity_threshold: medium
          confidence_threshold: medium
          skip_issues: false
          autofix_prs: true

      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: vibecheck-results
          path: .vibecheck-output/
          retention-days: 14
          if-no-files-found: ignore
"""


def get_vibecheck_workflow() -> str:
    """Return the vibecheck workflow YAML with the current VIBECHECK_REPO."""
    return _VIBECHECK_WORKFLOW_TEMPLATE.format(vibecheck_repo=VIBECHECK_REPO)
