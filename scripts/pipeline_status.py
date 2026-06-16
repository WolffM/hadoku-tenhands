"""
Pipeline status report for tenhands.
Reads local JSON state files and prints a formatted status summary.
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent / "backend" / ".cache" / "oss"


def load(name):
    path = ROOT / f"{name}.json"
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        print(f"[WARN] {name}.json is malformed: {e}", file=sys.stderr)
        return []


assignments = load("assignments")
ready = load("ready-to-submit")
submitted = load("submitted-prs")

# ── Submitted PRs ──────────────────────────────────────────────────────────────
merged = [p for p in submitted if p.get("merged")]
open_prs = [p for p in submitted if not p.get("merged") and p.get("state") == "open"]
closed_prs = [p for p in submitted if not p.get("merged") and p.get("state") not in ("open", None)]

print("## Submitted PRs (upstream)")
print(f"**{len(merged)} merged, {len(open_prs)} open, {len(closed_prs)} closed/rejected**")

if merged:
    print()
    print("### Merged")
    for p in merged:
        print(f"- ✅ [{p['origin_slug']}]({p['pr_url']}) — {p['title'][:80]}")

if open_prs:
    print()
    print("### Open")
    for p in open_prs:
        review = p.get("review_decision", "")
        review_str = f" [{review}]" if review else ""
        comments = p.get("comment_count", 0)
        comment_str = f" ({comments} comments)" if comments else ""
        print(f"- 🟢 [{p['origin_slug']}]({p['pr_url']}) — {p['title'][:70]}{review_str}{comment_str}")

if closed_prs:
    print()
    print("### Closed / Rejected")
    for p in closed_prs:
        print(f"- ❌ {p['origin_slug']} — {p['title'][:70]}")

# ── Ready to Submit ────────────────────────────────────────────────────────────
print()
print("## Ready to Submit (Stage 5)")

seen: set = set()
unique_ready = []
for r in ready:
    key = (r["origin_slug"], r["issue_number"])
    if key not in seen:
        seen.add(key)
        unique_ready.append(r)

if unique_ready:
    for r in unique_ready:
        fork_owner = "WolffM"
        fork_pulls = f"https://github.com/{fork_owner}/{r['repo']}/pulls"
        upstream_issue = f"https://github.com/{r['origin_slug']}/issues/{r['issue_number']}"
        print(f"- **[{r['origin_slug']} #{r['issue_number']}]({upstream_issue})** — {r['title']}")
        print(f"  Branch: `{r['branch']}` → [review fork PRs]({fork_pulls})")
else:
    print("_None_")

dup_count = len(ready) - len(unique_ready)
if dup_count:
    print(f"  _(Note: {dup_count} duplicate entries removed)_")

# ── Complete — Awaiting Stage 5 (human review needed) ─────────────────────────
TERMINAL = {"retrospective_complete"}
complete = [a for a in assignments if a.get("stage4_status") in TERMINAL]
active = [a for a in assignments if a.get("stage4_status") not in TERMINAL]

# Build lookup of already-submitted or ready-to-submit issues
submitted_keys = set((p["origin_slug"], p.get("issue_number")) for p in submitted)
ready_keys = set((r["origin_slug"], r["issue_number"]) for r in unique_ready)
submitted_slugs = set(p["origin_slug"] for p in submitted)

needs_stage5 = [
    a for a in complete
    if (a["origin_slug"], a["issue_number"]) not in submitted_keys
    and (a["origin_slug"], a["issue_number"]) not in ready_keys
]

print()
print("## Complete — Needs Stage 5 Review")
print(f"**{len(needs_stage5)} items finished fork cycle, not yet submitted upstream**")
if needs_stage5:
    print()
    for a in needs_stage5:
        fork_owner = "WolffM"
        repo = a.get("repo", "")
        fork_pr_num = a.get("stage4_pr_number")
        upstream_issue = f"https://github.com/{a['origin_slug']}/issues/{a['issue_number']}"
        if fork_pr_num:
            fork_link = f"https://github.com/{fork_owner}/{repo}/pull/{fork_pr_num}"
            links = f"[upstream issue]({upstream_issue}) · [fork PR #{fork_pr_num}]({fork_link})"
        else:
            fork_pulls = f"https://github.com/{fork_owner}/{repo}/pulls"
            links = f"[upstream issue]({upstream_issue}) · [fork PRs]({fork_pulls})"
        lang = a.get("language", "")
        lang_str = f" [{lang}]" if lang else ""
        print(f"- {a['origin_slug']} #{a['issue_number']}{lang_str} — {links}")

print()
print("## Active Assignments")
print(f"**{len(active)} active, {len(complete)} complete**")

STALL_HOURS = 12  # flag as stalled if swe_agent_working for longer than this

def _hours_since(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None

# Split swe_agent_working into stalled vs. genuinely recent
stalled = [
    a for a in active
    if a.get("stage4_status", "no_status") == "swe_agent_working"
    and (_hours_since(a.get("assigned_at")) or 0) > STALL_HOURS
]
stalled_keys = {(a["origin_slug"], a["issue_number"]) for a in stalled}
active_display = [a for a in active if (a["origin_slug"], a["issue_number"]) not in stalled_keys]

STATUS_ORDER = [
    "review_complete",
    "remediation_done",
    "static_analysis_done",
    "remediation_running",
    "review_in_progress",
    "static_analysis_running",
    "swe_agent_done",
    "swe_agent_working",
    "no_status",
]

STATUS_LABELS = {
    "review_complete":        "Review complete — ready for upstream",
    "remediation_done":       "Remediation done — SA re-run needed",
    "static_analysis_done":   "Static analysis done — review needed",
    "remediation_running":    "Remediation running",
    "review_in_progress":     "Under review",
    "static_analysis_running": "Static analysis running",
    "swe_agent_done":         "SWE agent done — SA running or queued",
    "swe_agent_working":      "SWE agent working (recent)",
    "no_status":              "Awaiting first poll",
}

seen_statuses = set(a.get("stage4_status", "no_status") for a in active_display)
ordered = STATUS_ORDER + sorted(seen_statuses - set(STATUS_ORDER))

for status in ordered:
    items = [a for a in active_display if a.get("stage4_status", "no_status") == status]
    if not items:
        continue
    label = STATUS_LABELS.get(status, status)
    print()
    print(f"### {label} ({len(items)})")
    for a in items:
        lang = a.get("language", "")
        lang_str = f" [{lang}]" if lang else ""
        tier = a.get("context_tier")
        tier_str = f" tier={tier}" if tier else ""
        fork_url = a.get("fork_issue_url", "")
        link = f" — [fork issue]({fork_url})" if fork_url else ""
        print(f"- {a['origin_slug']} #{a['issue_number']}{lang_str}{tier_str}{link}")

if stalled:
    print()
    print(f"### Agent stalled — no code commits after Initial Plan ({len(stalled)})")
    for a in stalled:
        hours = _hours_since(a.get("assigned_at"))
        age_str = f" ({int(hours)}h ago)" if hours else ""
        lang = a.get("language", "")
        lang_str = f" [{lang}]" if lang else ""
        fork_url = a.get("fork_issue_url", "")
        link = f" — [fork issue]({fork_url})" if fork_url else ""
        print(f"- {a['origin_slug']} #{a['issue_number']}{lang_str}{age_str}{link}")
