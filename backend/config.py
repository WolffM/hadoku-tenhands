"""
VibeDispatch Configuration Constants
"""

import os

# Platform constants - centralize here so they are easy to swap for other platforms
PLATFORM_PREFIX = "github"  # Used in issue ID format: "github-owner-repo-number"
COPILOT_ASSIGNEE = "@Copilot"
COPILOT_REVIEWER = "copilot-pull-request-reviewer[bot]"
COPILOT_MENTION = "@copilot"
COPILOT_CHECK_RUN_NAME = "Running Copilot coding agent"
GITHUB_NOREPLY_EMAIL_TEMPLATE = "{uid}+{login}@users.noreply.github.com"

# VibeCheck source repo — override with VIBECHECK_REPO env var (owner/repo format)
VIBECHECK_REPO = os.environ.get("VIBECHECK_REPO", "WolffM/vibecheck")

# VibeCheck workflow template
VIBECHECK_WORKFLOW = """name: vibeCheck
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
        uses: WolffM/vibecheck@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
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
