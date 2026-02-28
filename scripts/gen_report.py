#!/usr/bin/env python3
"""Generate pipeline-report.html from retrospective-logs.json + assignments.json.

Uses the shared report_generator module for HTML template and data assembly.
SA detail fetching (GitHub Actions API) runs here because it requires network calls
that are too slow for the real-time API endpoint.
"""
import json
import os
import subprocess
import sys

# Allow importing from backend
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.helpers.report_generator import (
    build_report_data,
    derive_slugs,
    render_report_html,
)

BASE = os.path.join(os.path.dirname(__file__), "..")
LOG_PATH = os.path.join(BASE, "backend", ".cache", "oss", "retrospective-logs.json")
ASSIGN_PATH = os.path.join(BASE, "backend", ".cache", "oss", "assignments.json")
OUT_PATH = os.path.join(BASE, "pipeline-report.html")

with open(LOG_PATH, "r", encoding="utf-8") as f:
    logs = json.load(f)
with open(ASSIGN_PATH, "r", encoding="utf-8") as f:
    assignments = json.load(f)


# ---------------------------------------------------------------------------
# Auto-detect target repo (CLI arg or most recent retro entry)
# ---------------------------------------------------------------------------
if len(sys.argv) > 1:
    REPO_NAME = sys.argv[1]
else:
    repo_counts = {}
    for e in logs:
        r = e.get("repo", "")
        if r:
            repo_counts[r] = repo_counts.get(r, 0) + 1
    REPO_NAME = max(repo_counts, key=lambda r: repo_counts[r]) if repo_counts else None
    if not REPO_NAME:
        print("No retrospective entries found.")
        sys.exit(1)

print(f"Generating report for: {REPO_NAME}")
ev = [e for e in logs if e.get("repo") == REPO_NAME]
ev_assign = [a for a in assignments if a.get("repo") == REPO_NAME]


# ---------------------------------------------------------------------------
# Derive fork slug for SA API calls
# ---------------------------------------------------------------------------
FORK_SLUG, ORIGIN_SLUG = derive_slugs(ev_assign)


# ---------------------------------------------------------------------------
# Fetch SA job-level details + annotations from GitHub Actions API
# ---------------------------------------------------------------------------
def _gh_json(args):
    """Run gh command and return parsed JSON, or None on failure."""
    try:
        r = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


def fetch_sa_details(run_id):
    """Fetch per-job conclusions and per-job annotations for a SA run."""
    if not run_id or not FORK_SLUG:
        return None

    jobs_data = _gh_json([
        "api", f"repos/{FORK_SLUG}/actions/runs/{run_id}/jobs",
        "--jq", ".jobs",
    ])
    if not jobs_data:
        return None

    result = {"jobs": [], "total_annotations": 0}
    for job in jobs_data:
        job_info = {
            "name": job.get("name", "unknown"),
            "conclusion": job.get("conclusion", "unknown"),
        }
        annotations = _gh_json([
            "api", f"repos/{FORK_SLUG}/check-runs/{job['id']}/annotations",
        ])
        if annotations:
            findings = [
                {
                    "path": a.get("path", ""),
                    "line": a.get("start_line", 0),
                    "level": a.get("annotation_level", ""),
                    "message": a.get("message", ""),
                }
                for a in annotations
                if a.get("path", "") != ".github"
            ]
            job_info["annotations"] = findings
            result["total_annotations"] += len(findings)
        else:
            job_info["annotations"] = []
        result["jobs"].append(job_info)

    return result


# Backfill SA job details for entries that lack them (old logs).
# New pipeline runs capture jobs at write time, so skip those.
sa_cache = {}
needs_fetch = [e for e in ev
               if e.get("static_analysis", {}).get("run_id")
               and not e.get("static_analysis", {}).get("jobs")]
if needs_fetch:
    print(f"Fetching SA job details for {len(needs_fetch)} entries...")
    for entry in needs_fetch:
        rid = entry["static_analysis"]["run_id"]
        if rid not in sa_cache:
            print(f"  Fetching run {rid}...")
            sa_cache[rid] = fetch_sa_details(rid)
    for entry in needs_fetch:
        rid = entry["static_analysis"]["run_id"]
        if sa_cache.get(rid):
            entry["static_analysis"]["jobs"] = sa_cache[rid]["jobs"]
            entry["static_analysis"]["total_annotations"] = sa_cache[rid]["total_annotations"]
else:
    print("All entries already have SA job details — skipping API fetch.")


# ---------------------------------------------------------------------------
# Build report using shared module and render
# ---------------------------------------------------------------------------
report_data = build_report_data(REPO_NAME, ev, ev_assign)
html = render_report_html(report_data)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Written {OUT_PATH}")
for rd in report_data["runs"]:
    print(f"  {rd['label']} ({rd['tag']}): {len(rd['entries'])} entries")
