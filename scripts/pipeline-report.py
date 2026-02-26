#!/usr/bin/env python3
"""
Pipeline Report — reads retrospective-logs.json and renders a comparison table.

Usage:
    python scripts/pipeline-report.py                     # all entries
    python scripts/pipeline-report.py --repo email-verifier  # filter by repo
    python scripts/pipeline-report.py --json              # raw JSON output
"""

import argparse
import json
import os
import sys

DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "backend", ".cache", "oss", "retrospective-logs.json"
)


def load_logs(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def render_table(entries):
    if not entries:
        print("No retrospective logs found.")
        return

    # Header
    cols = [
        ("Issue", 7), ("PR", 5), ("+/-", 10), ("Files", 5),
        ("Commits", 7), ("SA", 10), ("Review", 12),
        ("Remed", 8),
    ]
    header = "  ".join(name.ljust(width) for name, width in cols)
    print(header)
    print("-" * len(header))

    for e in entries:
        issue = f"#{e.get('issue_number', '?')}"
        swe = e.get("swe", {})
        pr = f"#{swe.get('pr_number', '?')}"

        additions = swe.get("additions", 0)
        deletions = swe.get("deletions", 0)
        diff = f"+{additions}/-{deletions}"
        files = str(swe.get("changed_files", swe.get("commit_count", "?")))
        commits = str(swe.get("commit_count", "?"))

        sa = e.get("static_analysis", {})
        sa_text = sa.get("conclusion", "?")

        review = e.get("review", {})
        review_count = review.get("inline_comment_count", 0)
        review_text = f"{review_count} comments"

        remed = e.get("remediation", {})
        if remed.get("skipped"):
            remed_text = "skip"
        else:
            new = remed.get("new_commits", "?")
            remed_text = f"{new} commit" if new != "?" else "done"

        row = [
            issue.ljust(7), pr.ljust(5), diff.ljust(10), files.ljust(5),
            commits.ljust(7), sa_text.ljust(10), review_text.ljust(12),
            remed_text.ljust(8),
        ]
        print("  ".join(row))


def main():
    parser = argparse.ArgumentParser(description="Pipeline retrospective report")
    parser.add_argument("--path", default=DEFAULT_LOG_PATH,
                        help="Path to retrospective-logs.json")
    parser.add_argument("--repo", help="Filter by repo name")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output raw JSON")
    args = parser.parse_args()

    entries = load_logs(args.path)

    if args.repo:
        entries = [e for e in entries if e.get("repo") == args.repo]

    if args.json_output:
        print(json.dumps(entries, indent=2))
    else:
        render_table(entries)


if __name__ == "__main__":
    main()
