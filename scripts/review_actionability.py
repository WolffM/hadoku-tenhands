"""Cherry-pick review tool for actionability decisions.

Combines a backfill result (rubric verdict + evidence) with a live re-fetch
of the issue body + comments, formatted as markdown so the operator can
manually validate any decision point.

Usage:
  # Single issue → stdout
  python3 scripts/review_actionability.py keycloak/keycloak 46523

  # All backfilled issues → scripts/backfill_output/reviews/*.md
  python3 scripts/review_actionability.py --all

  # Filtered: only show disagree_pass cases
  python3 scripts/review_actionability.py --filter disagree_pass

  # Filtered: only the 5 smoke-test issues
  python3 scripts/review_actionability.py --smoke-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import smoke_actionability as smoke  # noqa: E402

BACKFILL_DIR = REPO_ROOT / "scripts" / "backfill_output"
REVIEWS_DIR = BACKFILL_DIR / "reviews"
REVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def _find_backfill_result(slug: str, number: int) -> dict | None:
    """Locate the backfill output JSON for a given slug+number, if any."""
    needle = f"{slug.replace('/', '__')}-{number}.json"
    for f in BACKFILL_DIR.glob("*.json"):
        if f.name.endswith(needle):
            return json.loads(f.read_text())
    return None


def _operator_context(slug: str, number: int) -> dict:
    """Read the original operator-side context (override decision, last transition)
    from the historical state dir, if present."""
    needle_dir = f"{slug.replace('/', '__')}-{number}"
    ctx: dict = {}
    state_root = REPO_ROOT / "state"
    if not state_root.exists():
        return ctx
    for batch in state_root.iterdir():
        if not batch.is_dir():
            continue
        candidate = batch / needle_dir
        if not candidate.is_dir():
            continue
        ctx["batch_id"] = batch.name
        override_p = candidate / "awaiting" / "override_decision.json"
        if override_p.exists():
            try:
                ctx["override"] = json.loads(override_p.read_text())
            except Exception:
                pass
        transitions_p = candidate / "transitions.jsonl"
        if transitions_p.exists():
            last_line = None
            for raw in transitions_p.read_text().splitlines():
                if raw.strip():
                    last_line = raw
            if last_line:
                try:
                    ctx["last_transition"] = json.loads(last_line)
                except Exception:
                    pass
        outcomes_p = candidate / "outcomes" / "upstream_state.json"
        if outcomes_p.exists():
            try:
                ctx["outcome"] = json.loads(outcomes_p.read_text())
            except Exception:
                pass
        break  # first match is enough
    return ctx


def render_markdown(slug: str, number: int) -> str:
    """Compose the full review markdown for one issue."""
    print(f"  fetching {slug}#{number}...", file=sys.stderr, flush=True)
    data = smoke.fetch_issue_data(slug, number)
    if data.get("errors"):
        return f"# {slug}#{number}\n\n!! Fetch errors: {data['errors']}\n"

    flags = smoke.compute_flags(data)
    backfill = _find_backfill_result(slug, number)
    op_ctx = _operator_context(slug, number)

    lines: list[str] = []
    lines.append(f"# {slug}#{number}: {data.get('title','')}")
    lines.append("")
    lines.append(f"**Issue:** https://github.com/{slug}/issues/{number}")
    lines.append(f"**Labels:** {', '.join(data.get('labels', [])) or '_(none)_'}")
    lines.append(f"**Updated:** {data.get('updated_at')}")
    lines.append(f"**Comment count (fetched):** {len(data.get('comments', []))}")
    lines.append(f"**Sub-issue count:** {data.get('sub_issues',{}).get('count', 0)}")
    lines.append(f"**Linked PRs:** {len(data.get('linked_pr_urls') or [])}")
    if data.get('linked_pr_urls'):
        for u in data['linked_pr_urls'][:8]:
            lines.append(f"  - {u}")
    lines.append(f"**Computed flags:** {flags or '_(none)_'}")
    lines.append("")

    if op_ctx:
        lines.append("---")
        lines.append("")
        lines.append("## Operator-side context")
        lines.append("")
        if op_ctx.get("batch_id"):
            lines.append(f"- **batch_id:** `{op_ctx['batch_id']}`")
        if op_ctx.get("outcome"):
            lines.append(f"- **outcome state:** `{op_ctx['outcome'].get('state','?')}`")
        if op_ctx.get("override"):
            ov = op_ctx["override"]
            lines.append(f"- **operator decision:** `{ov.get('decision','?')}` ({ov.get('reason_code','no code')})")
            if ov.get("reason_text"):
                lines.append(f"- **operator reason text:** {ov['reason_text']}")
            lines.append(f"- **decided at:** {ov.get('at','?')}")
        if op_ctx.get("last_transition"):
            lt = op_ctx["last_transition"]
            lines.append(f"- **last pipeline transition:** `{lt.get('to','?')}` — {(lt.get('reason') or '')[:200]}")
        lines.append("")

    if backfill:
        lines.append("---")
        lines.append("")
        lines.append("## Rubric verdict (from backfill)")
        lines.append("")
        lines.append(f"- **Verdict:** `{backfill.get('rubric_verdict','?')}`")
        lines.append(f"- **Score:** `{backfill.get('rubric_score','?')}`")
        lines.append(f"- **Agreement class:** `{backfill.get('agreement','?')}`")
        lines.append("")
        lines.append("**Reasoning:**")
        lines.append("")
        lines.append("> " + (backfill.get('rubric_reasoning') or '').replace("\n", "\n> "))
        lines.append("")
        ev = backfill.get("rubric_evidence") or []
        if ev:
            lines.append(f"**Evidence ({len(ev)} entries):**")
            lines.append("")
            for e in ev:
                sev = e.get("severity", "?")
                dr = e.get("direction", "?")
                sig = e.get("signal", "?")
                quote = (e.get("quote") or "").replace("\n", " ")[:240]
                auth = e.get("comment_author") or "?"
                at = e.get("at") or "?"
                lines.append(f"- **[{sev}/{dr}]** `{sig}` — {auth} @ {at}")
                lines.append(f"  > {quote}")
            lines.append("")
    else:
        lines.append("---")
        lines.append("")
        lines.append("## Rubric verdict")
        lines.append("")
        lines.append(f"_(No backfill result on disk for {slug}#{number}. Run the backfill or smoke driver against this issue to get a verdict.)_")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Issue body")
    lines.append("")
    body = (data.get("body") or "").strip()
    if body:
        lines.append(body)
    else:
        lines.append("_(empty)_")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"## Comment thread ({len(data.get('comments', []))} comments, chronological)")
    lines.append("")
    if not data.get("comments"):
        lines.append("_(no comments)_")
    else:
        for c in data["comments"]:
            kind = "🤖 BOT" if c["is_bot"] else ("🛠 MAINTAINER" if c["is_maintainer"] else "👤 user")
            lines.append(f"### {kind} `{c['author']}` — {c['at']} _(assoc: {c['association']})_")
            lines.append("")
            body = (c.get("body") or "").strip()
            if body:
                # Indent quoted body so headers in comments don't collide with our outline
                for ln in body.split("\n"):
                    lines.append(f"> {ln}")
            else:
                lines.append("> _(empty)_")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Recent timeline events (last 180 days, non-comment)")
    lines.append("")
    events = data.get("recent_timeline_events") or []
    if not events:
        lines.append("_(none)_")
    else:
        for ev in events:
            evt = ev.get("event", "?")
            actor = ev.get("actor", "?")
            at = ev.get("at", "?")
            detail = ev.get("detail", "")
            line = f"- `{evt}` by `{actor}` @ {at}"
            if detail:
                line += f" — {detail}"
            lines.append(line)
    lines.append("")

    return "\n".join(lines)


def _collect_backfill_targets(filt: str | None) -> list[tuple[str, int]]:
    """Walk backfill_output/ and return (slug, number) pairs matching filter."""
    targets: list[tuple[str, int]] = []
    for f in sorted(BACKFILL_DIR.glob("*.json")):
        if f.name == "_summary.json":
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if filt and d.get("agreement") != filt:
            continue
        slug = d.get("slug")
        num = d.get("number")
        if slug and num:
            targets.append((slug, int(num)))
    # Dedupe (an issue can be in multiple batches)
    seen = set()
    deduped: list[tuple[str, int]] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


_SMOKE_SET = [
    ("keycloak/keycloak", 46523),
    ("microsoft/pyright", 11408),
    ("docker/compose", 9026),
    ("obsidian-tasks-group/obsidian-tasks", 1016),
    ("microsoft/monaco-editor", 3336),
]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="upstream slug, e.g. keycloak/keycloak")
    ap.add_argument("number", nargs="?", type=int, help="issue number")
    ap.add_argument("--all", action="store_true",
                    help="Render all backfilled issues to scripts/backfill_output/reviews/")
    ap.add_argument("--filter", choices=["agree_fail", "agree_defer", "softer_defer", "disagree_pass"],
                    help="Only render issues with this agreement class (use with --all)")
    ap.add_argument("--smoke-only", action="store_true",
                    help="Render just the 5 smoke-test issues")
    args = ap.parse_args(argv)

    if args.slug and args.number:
        # Single-issue → stdout
        print(render_markdown(args.slug, args.number))
        return 0

    if args.smoke_only:
        targets = _SMOKE_SET
    elif args.all:
        targets = _collect_backfill_targets(args.filter)
    else:
        ap.print_help()
        return 1

    print(f"Rendering {len(targets)} reviews to {REVIEWS_DIR}/", file=sys.stderr)
    for slug, number in targets:
        md = render_markdown(slug, number)
        out = REVIEWS_DIR / f"{slug.replace('/', '__')}-{number}.md"
        out.write_text(md, encoding="utf-8")
        print(f"  → {out.name}", file=sys.stderr)
    print(f"\nDone. Reviews in {REVIEWS_DIR}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
