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

    yn = lambda v: "YES" if v else "no "

    # Header
    cols = [
        ("Issue", 7), ("PR", 5), ("+/-", 10), ("Files", 5),
        ("SA", 8), ("Review", 8), ("Remed", 6),
        ("Repro", 5), ("Verify", 6), ("SelfFx", 6), ("Steps", 5),
        ("Tier", 4), ("Agent", 12),
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
        files = str(swe.get("changed_files", "?"))

        sa = e.get("static_analysis", {})
        sa_text = sa.get("conclusion", "?")[:8]

        review = e.get("review", {})
        review_count = review.get("inline_comment_count", 0)
        review_text = f"{review_count} cmts"

        remed = e.get("remediation", {})
        if remed.get("skipped"):
            remed_text = "skip"
        else:
            new = remed.get("new_commits", "?")
            remed_text = f"+{new}" if new != "?" else "done"

        wf = e.get("workflow", {})
        repro = yn(wf.get("reproduced"))
        verify = yn(wf.get("verified"))
        selffix = yn(wf.get("self_corrected"))
        steps = str(wf.get("step_count", "?"))

        pl = e.get("pipeline", {})
        agent = pl.get("swe_agent", "?").replace("Dispatcher", "")[:12]

        dq = e.get("data_quality", {})
        tier = str(dq.get("context_tier", "?"))

        row = [
            issue.ljust(7), pr.ljust(5), diff.ljust(10), files.ljust(5),
            sa_text.ljust(8), review_text.ljust(8), remed_text.ljust(6),
            repro.ljust(5), verify.ljust(6), selffix.ljust(6), steps.ljust(5),
            tier.ljust(4), agent.ljust(12),
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
