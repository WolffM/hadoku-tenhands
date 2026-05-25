"""Render every backfilled actionability decision as a single HTML page.

Self-contained: embeds CSS, no external assets. Output is a single .html
file with a TOC at the top (grouped by agreement class), collapsible
sections per issue, color-coded verdict badges, and the full issue body
+ comment thread + rubric evidence inline so an operator can cherry-pick
review without re-fetching.

Usage:
  python3 scripts/render_actionability_html.py [--out /tmp/foo.html]
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import smoke_actionability as smoke  # noqa: E402

BACKFILL_DIR = REPO_ROOT / "scripts" / "backfill_output"


# ── shared CSS ──────────────────────────────────────────────────────────


CSS = """
:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --border: #e0e4ea;
  --text: #1c2530;
  --muted: #5a6573;
  --pass: #058036;
  --pass-bg: #d8f4e2;
  --defer: #b97400;
  --defer-bg: #fcedc7;
  --fail: #b32424;
  --fail-bg: #fde0e0;
  --link: #0a64c2;
  --code-bg: #f0f2f6;
}
* { box-sizing: border-box; }
html, body { overflow-x: hidden; }
body {
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background: var(--bg); color: var(--text);
  margin: 0; padding: 0;
  max-width: 100vw;
}
header {
  background: var(--text); color: #f6f8fb;
  padding: 18px 28px; position: sticky; top: 0; z-index: 5;
  box-shadow: 0 2px 8px rgba(0,0,0,.12);
}
header h1 { margin: 0 0 6px; font-size: 18px; }
header .sub { color: #b5c0cf; font-size: 13px; }
.layout {
  display: grid; grid-template-columns: 280px minmax(0, 1fr);
  max-width: 1500px; margin: 0 auto;
}
nav.toc {
  background: var(--card); border-right: 1px solid var(--border);
  padding: 18px; position: sticky; top: 0; height: 100vh;
  overflow-y: auto;
  min-width: 0;
}
nav.toc h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em;
             color: var(--muted); margin: 14px 0 6px; }
nav.toc h3:first-of-type { margin-top: 0; }
nav.toc a {
  display: block; padding: 4px 8px; border-radius: 4px;
  text-decoration: none; color: var(--text); font-size: 13px;
  margin-bottom: 1px;
  overflow-wrap: anywhere;
}
nav.toc a:hover { background: var(--bg); }
nav.toc a code { font-size: 12px; color: var(--muted); }
main {
  padding: 24px 28px 80px;
  min-width: 0;
  max-width: 100%;
}
.issue {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 28px; overflow: hidden;
  max-width: 100%;
}
.issue-header { padding: 16px 20px; border-bottom: 1px solid var(--border); }
.issue-header h2 {
  margin: 0 0 6px; font-size: 17px;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  overflow-wrap: anywhere;
}
.issue-header h2 a { color: var(--text); text-decoration: none; }
.issue-header h2 a:hover { color: var(--link); }
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em;
}
.badge.pass { background: var(--pass-bg); color: var(--pass); }
.badge.defer { background: var(--defer-bg); color: var(--defer); }
.badge.fail { background: var(--fail-bg); color: var(--fail); }
.badge.muted { background: var(--code-bg); color: var(--muted); }
.meta-grid {
  display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 16px;
  font-size: 13px; padding: 16px 20px;
}
.meta-grid dt { color: var(--muted); }
.meta-grid dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.meta-grid dd a { color: var(--link); text-decoration: none; overflow-wrap: anywhere; }
.meta-grid dd a:hover { text-decoration: underline; }
.meta-grid dd code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px; font-size: 12px; overflow-wrap: anywhere; }
.section { padding: 16px 20px; border-top: 1px solid var(--border); min-width: 0; }
.section h3 { margin: 0 0 12px; font-size: 14px; text-transform: uppercase;
              letter-spacing: .04em; color: var(--muted); }
.reasoning {
  background: var(--code-bg); padding: 12px 14px; border-radius: 6px;
  margin: 0 0 12px; font-size: 14px;
  overflow-wrap: anywhere; word-break: break-word;
}
.evidence { margin: 0; padding: 0; list-style: none; }
.evidence li {
  padding: 10px 12px; border-left: 3px solid var(--border);
  margin: 0 0 8px; font-size: 13px; background: #fafbfd;
  overflow-wrap: anywhere;
}
.evidence li.severity-blocking { border-left-color: #b32424; }
.evidence li.severity-strong { border-left-color: #b97400; }
.evidence li.severity-weak { border-left-color: var(--border); }
.evidence li.direction-reward { background: #f3faf5; }
.evidence-meta { color: var(--muted); font-size: 12px; margin-bottom: 4px;
                 overflow-wrap: anywhere; }
.evidence-quote {
  font-style: italic; color: var(--text);
  border-left: 2px solid var(--border); padding-left: 10px;
  margin-top: 6px;
  white-space: pre-wrap;
  overflow-wrap: anywhere; word-break: break-word;
}
.comment {
  padding: 10px 12px; margin: 0 0 10px;
  border-left: 3px solid var(--border); background: #fafbfd;
  overflow: hidden;
}
.comment.maintainer { border-left-color: var(--pass); background: #f3faf5; }
.comment.bot { border-left-color: var(--muted); opacity: 0.7; }
.comment-author { font-weight: 600; font-size: 13px; overflow-wrap: anywhere; }
.comment-meta { color: var(--muted); font-size: 12px; margin-bottom: 8px;
                overflow-wrap: anywhere; }
.comment-body {
  white-space: pre-wrap; font-size: 14px;
  overflow-wrap: anywhere; word-break: break-word;
}
.body-pre {
  white-space: pre-wrap; background: var(--code-bg); padding: 12px;
  border-radius: 6px; font-size: 13px;
  max-height: 400px; overflow-y: auto; overflow-x: hidden;
  overflow-wrap: anywhere; word-break: break-word;
}
details { margin-top: 4px; }
details summary { cursor: pointer; color: var(--muted); font-size: 13px; }
details > div { margin-top: 8px; overflow-wrap: anywhere; }
code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere; word-break: break-word;
}
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; }
  nav.toc { position: static; height: auto; max-height: 40vh; border-right: none;
            border-bottom: 1px solid var(--border); }
}

/* Show one issue at a time. Driven by a JS-managed `.shown` class on
   the issue elements — NOT :target, because history.replaceState
   doesn't re-trigger :target in browsers, which broke selection after
   the first click. */
.issue { display: none; }
.issue.shown { display: block; }
.welcome {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 32px 28px; color: var(--muted);
  max-width: 720px; margin: 0 auto;
}
.welcome h2 { color: var(--text); margin: 0 0 12px; font-size: 18px; }
.welcome p { margin: 4px 0; font-size: 14px; }
.welcome ul { padding-left: 18px; font-size: 14px; }
.welcome.hidden { display: none; }
nav.toc a.active {
  background: var(--code-bg); font-weight: 600; color: var(--text);
}
"""


def _h(s) -> str:
    """HTML-escape, accepting None gracefully."""
    if s is None:
        return ""
    return html.escape(str(s))


def _find_backfill_result(slug: str, number: int) -> dict | None:
    needle = f"{slug.replace('/', '__')}-{number}.json"
    for f in BACKFILL_DIR.glob("*.json"):
        if f.name.endswith(needle):
            return json.loads(f.read_text())
    return None


def _operator_context(slug: str, number: int) -> dict:
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
        # submission_judge — the judge that scored the AGENT'S PR at end
        # of pipeline. Distinct from actionability rubric (which judges
        # the ISSUE). Surfaced so operator can compare the two judges
        # side by side: rubric says "should we dispatch this issue?",
        # submission_judge said "is the resulting PR shippable?".
        sj_p = candidate / "09-submittable" / "submission_judge.json"
        if sj_p.exists():
            try:
                ctx["submission_judge"] = json.loads(sj_p.read_text())
            except Exception:
                pass
        break
    return ctx


def _verdict_class(verdict: str) -> str:
    return {"pass": "pass", "defer": "defer", "fail": "fail"}.get(verdict, "muted")


def render_issue_html(slug: str, number: int, anchor: str) -> tuple[str, dict]:
    """Render one issue's review as HTML. Returns (html, summary_dict)."""
    print(f"  fetching {slug}#{number}...", file=sys.stderr, flush=True)
    data = smoke.fetch_issue_data(slug, number)
    if data.get("errors"):
        return (
            f'<section class="issue" id="{anchor}"><div class="issue-header">'
            f'<h2>{_h(slug)}#{number} <span class="badge muted">fetch error</span></h2>'
            f'<div class="meta-grid"><dt>errors</dt><dd>{_h(data["errors"])}</dd></div>'
            f'</div></section>',
            {"slug": slug, "number": number, "anchor": anchor, "verdict": "fetch_error",
             "agreement": "error", "title": ""},
        )

    flags = smoke.compute_flags(data)
    backfill = _find_backfill_result(slug, number)
    op_ctx = _operator_context(slug, number)

    title = data.get("title", "")
    verdict = (backfill or {}).get("rubric_verdict", "?") if backfill else "no_run"
    score = (backfill or {}).get("rubric_score")
    agreement = (backfill or {}).get("agreement", "?")
    v_class = _verdict_class(verdict)

    parts: list[str] = []
    parts.append(f'<section class="issue" id="{anchor}">')

    # Header
    parts.append('<div class="issue-header">')
    parts.append(
        f'<h2><a href="https://github.com/{_h(slug)}/issues/{number}" target="_blank">'
        f'{_h(slug)}#{number}</a>: {_h(title)} '
        f'<span class="badge {v_class}">{_h(verdict)}'
        + (f' {score:.2f}' if isinstance(score, (int, float)) else "")
        + '</span> '
        f'<span class="badge muted">{_h(agreement)}</span></h2>'
    )
    parts.append('</div>')

    # Metadata grid
    parts.append('<dl class="meta-grid">')
    parts.append(f'<dt>labels</dt><dd>{_h(", ".join(data.get("labels", [])) or "—")}</dd>')
    parts.append(f'<dt>updated</dt><dd>{_h(data.get("updated_at"))}</dd>')
    parts.append(f'<dt>comments (fetched)</dt><dd>{len(data.get("comments", []))}</dd>')
    parts.append(f'<dt>sub-issues</dt><dd>{data.get("sub_issues", {}).get("count", 0)}</dd>')
    linked = data.get("linked_pr_urls") or []
    parts.append(f'<dt>linked PRs</dt><dd>{len(linked)}')
    if linked:
        parts.append('<details><summary>show</summary><div>')
        for u in linked[:12]:
            parts.append(f'<a href="{_h(u)}" target="_blank">{_h(u)}</a><br>')
        parts.append('</div></details>')
    parts.append('</dd>')
    parts.append(f'<dt>computed flags</dt><dd>{_h(", ".join(flags) or "—")}</dd>')
    parts.append('</dl>')

    # Operator-side context
    if op_ctx:
        parts.append('<div class="section">')
        parts.append('<h3>Operator-side context</h3>')
        parts.append('<dl class="meta-grid">')
        if op_ctx.get("batch_id"):
            parts.append(f'<dt>batch</dt><dd><code>{_h(op_ctx["batch_id"])}</code></dd>')
        if op_ctx.get("outcome"):
            parts.append(f'<dt>outcome state</dt><dd><code>{_h(op_ctx["outcome"].get("state", "?"))}</code></dd>')
        if op_ctx.get("override"):
            ov = op_ctx["override"]
            parts.append(f'<dt>operator decision</dt><dd><code>{_h(ov.get("decision","?"))}</code> ({_h(ov.get("reason_code","no code"))})</dd>')
            if ov.get("reason_text"):
                parts.append(f'<dt>operator reason</dt><dd>{_h(ov["reason_text"])}</dd>')
        if op_ctx.get("last_transition"):
            lt = op_ctx["last_transition"]
            parts.append(f'<dt>last transition</dt><dd><code>{_h(lt.get("to","?"))}</code> — {_h((lt.get("reason") or "")[:240])}</dd>')
        # Surface the historical submission_judge verdict — same shape as
        # the rubric verdict block below, just from a different judge that
        # ran post-fix at end of pipeline.
        if op_ctx.get("submission_judge"):
            sj = op_ctx["submission_judge"]
            sj_v = sj.get("verdict") or "?"
            sj_class = _verdict_class(sj_v)
            sj_score = sj.get("score")
            score_str = f" {sj_score:.2f}" if isinstance(sj_score, (int, float)) else ""
            parts.append(
                f'<dt>submission_judge</dt>'
                f'<dd><span class="badge {sj_class}">{_h(sj_v)}{score_str}</span>'
            )
            if sj.get("reasoning"):
                parts.append(f'<div class="reasoning" style="margin-top:8px;font-size:13px;">{_h((sj.get("reasoning") or "")[:600])}</div>')
            parts.append('</dd>')
        parts.append('</dl>')
        parts.append('</div>')

    # Rubric verdict
    if backfill:
        parts.append('<div class="section">')
        parts.append('<h3>Rubric verdict</h3>')
        reasoning = backfill.get("rubric_reasoning") or ""
        if reasoning:
            parts.append(f'<div class="reasoning">{_h(reasoning)}</div>')
        evidence = backfill.get("rubric_evidence") or []
        if evidence:
            parts.append(f'<ul class="evidence">')
            for e in evidence:
                sev = e.get("severity", "?")
                direction = e.get("direction", "?")
                signal = e.get("signal", "?")
                author = e.get("comment_author") or "?"
                at = e.get("at") or "?"
                quote = e.get("quote") or ""
                parts.append(
                    f'<li class="severity-{_h(sev)} direction-{_h(direction)}">'
                    f'<div class="evidence-meta"><strong>{_h(sev)}/{_h(direction)}</strong> '
                    f'<code>{_h(signal)}</code> — {_h(author)} @ {_h(at)}</div>'
                    f'<div class="evidence-quote">{_h(quote)}</div>'
                    f'</li>'
                )
            parts.append('</ul>')
        parts.append('</div>')
    else:
        parts.append('<div class="section">')
        parts.append('<h3>Rubric verdict</h3>')
        parts.append('<p style="color:var(--muted);font-size:13px;">No backfill result on disk for this issue.</p>')
        parts.append('</div>')

    # Issue body
    parts.append('<div class="section">')
    parts.append('<h3>Issue body</h3>')
    body = (data.get("body") or "").strip() or "(empty)"
    parts.append(f'<div class="body-pre">{_h(body)}</div>')
    parts.append('</div>')

    # Comments
    parts.append('<div class="section">')
    parts.append(f'<h3>Comment thread ({len(data.get("comments", []))})</h3>')
    if not data.get("comments"):
        parts.append('<p style="color:var(--muted);font-size:13px;">No comments.</p>')
    else:
        for c in data["comments"]:
            kind = "bot" if c["is_bot"] else ("maintainer" if c["is_maintainer"] else "user")
            kind_label = "🤖 BOT" if c["is_bot"] else ("🛠 MAINTAINER" if c["is_maintainer"] else "👤")
            parts.append(f'<div class="comment {kind}">')
            parts.append(
                f'<div class="comment-author">{kind_label} {_h(c["author"])}</div>'
                f'<div class="comment-meta">{_h(c["at"])} · assoc: {_h(c["association"])}</div>'
                f'<div class="comment-body">{_h((c.get("body") or "").strip()) or "<em>(empty)</em>"}</div>'
            )
            parts.append('</div>')
    parts.append('</div>')

    # Timeline
    parts.append('<div class="section">')
    parts.append('<h3>Recent timeline events (180d)</h3>')
    events = data.get("recent_timeline_events") or []
    if not events:
        parts.append('<p style="color:var(--muted);font-size:13px;">None.</p>')
    else:
        parts.append('<ul style="margin:0;padding-left:18px;font-size:13px;">')
        for ev in events:
            evt = ev.get("event", "?")
            actor = ev.get("actor", "?")
            at = ev.get("at", "?")
            detail = ev.get("detail", "")
            extra = f' — {_h(detail)}' if detail else ""
            parts.append(f'<li><code>{_h(evt)}</code> by <code>{_h(actor)}</code> @ {_h(at)}{extra}</li>')
        parts.append('</ul>')
    parts.append('</div>')

    parts.append('</section>')

    summary = {
        "slug": slug, "number": number, "anchor": anchor,
        "verdict": verdict, "score": score,
        "agreement": agreement, "title": title,
    }
    return "\n".join(parts), summary


def render_full_page(targets: list[tuple[str, int]]) -> str:
    """Render the full HTML page across all targets."""
    issues_html: list[str] = []
    summaries: list[dict] = []
    for slug, number in targets:
        anchor = f"i-{slug.replace('/', '_')}-{number}"
        section, summary = render_issue_html(slug, number, anchor)
        issues_html.append(section)
        summaries.append(summary)

    # TOC grouped by agreement class
    by_agreement: dict[str, list[dict]] = defaultdict(list)
    for s in summaries:
        by_agreement[s.get("agreement", "?")].append(s)

    toc_parts = ['<nav class="toc">']
    toc_parts.append('<h3>Quick stats</h3>')
    toc_parts.append(f'<a><code>{len(summaries)} issues</code></a>')
    for k in ("disagree_pass", "softer_defer", "agree_fail", "agree_defer", "error"):
        if k in by_agreement:
            toc_parts.append(f'<a><code>{k}: {len(by_agreement[k])}</code></a>')
    # Sidebar order: smallest groups first so all sections stay above the
    # sidebar's fold on a typical viewport. agree_fail is the biggest
    # group; it goes last.
    order = ["disagree_pass", "softer_defer", "agree_defer", "agree_fail", "error", "?"]
    for cls in order:
        if cls not in by_agreement:
            continue
        toc_parts.append(f'<h3>{_h(cls)}</h3>')
        for s in by_agreement[cls]:
            v_class = _verdict_class(s.get("verdict", ""))
            label = f'{s["slug"]}#{s["number"]}'
            toc_parts.append(
                f'<a href="#{s["anchor"]}">'
                f'<span class="badge {v_class}" style="font-size:9px;padding:1px 5px;">{_h(s.get("verdict","?"))}</span> '
                f'<code>{_h(label)}</code></a>'
            )
    toc_parts.append('</nav>')

    # Top header dropped per operator request — page goes straight to the
    # sidebar + main layout.
    head = ""

    # Welcome card shown when no issue is selected (no URL hash matching an .issue id)
    counts = ", ".join(f"{k}: {len(v)}" for k, v in by_agreement.items())
    welcome = (
        '<div class="welcome">'
        '<h2>Pick an issue from the sidebar</h2>'
        f'<p>{len(summaries)} issues in the calibration corpus.</p>'
        f'<p><strong>Agreement breakdown:</strong> {_h(counts)}</p>'
        '<p>Each link in the sidebar opens one issue. Use browser back/forward to'
        ' move between selections; the URL hash holds the current issue id.</p>'
        '</div>'
    )

    # JS drives both visibility AND URL. We can't use CSS :target because
    # history.replaceState doesn't re-evaluate :target in browsers — first
    # click worked, subsequent clicks left the first-shown issue stuck.
    # Now: clicking a TOC link toggles a `.shown` class on the matching
    # issue (and hides the welcome), updates the URL bar for bookmark/
    # back-forward support, and resets scroll-to-top for consistent
    # placement. No browser auto-scroll.
    script = (
        "<script>"
        "function applyHash(href){"
        "  var id=(href||'').replace(/^#/,'');"
        "  if(href && href.startsWith('#') && href !== location.hash){"
        "    history.replaceState(null,'',href);"
        "  }"
        "  document.querySelectorAll('.issue').forEach(function(el){"
        "    el.classList.toggle('shown', el.id===id && id!=='');"
        "  });"
        "  var w=document.querySelector('.welcome');"
        "  if(w) w.classList.toggle('hidden', id!=='');"
        "  document.querySelectorAll('nav.toc a').forEach(function(a){"
        "    a.classList.toggle('active', a.getAttribute('href')===href);"
        "  });"
        "  window.scrollTo(0,0);"
        "}"
        "document.querySelectorAll('nav.toc a').forEach(function(a){"
        "  var href=a.getAttribute('href');"
        "  if(!href||!href.startsWith('#'))return;"
        "  a.addEventListener('click',function(e){"
        "    e.preventDefault();"
        "    applyHash(href);"
        "  });"
        "});"
        "window.addEventListener('popstate',function(){applyHash(location.hash);});"
        "applyHash(location.hash);"
        "</script>"
    )

    return (
        '<!DOCTYPE html>\n<html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Actionability rubric — cherry-pick review</title>'
        f'<style>{CSS}</style>'
        '</head><body>'
        + head
        + '<div class="layout">'
        + "\n".join(toc_parts)
        + '<main>'
        + welcome
        + "\n".join(issues_html)
        + '</main></div>'
        + script
        + '</body></html>'
    )


def _collect_targets(filt: str | None) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = []
    seen = set()
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
        if slug and num and (slug, int(num)) not in seen:
            seen.add((slug, int(num)))
            targets.append((slug, int(num)))
    return targets


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/actionability_reviews.html",
                    help="Path to write the HTML file")
    ap.add_argument("--filter", choices=["agree_fail", "agree_defer", "softer_defer", "disagree_pass"],
                    help="Only render issues with this agreement class")
    args = ap.parse_args(argv)

    targets = _collect_targets(args.filter)
    if not targets:
        print("No backfill targets found.", file=sys.stderr)
        return 1
    print(f"Rendering {len(targets)} issues to {args.out}", file=sys.stderr)

    html_doc = render_full_page(targets)
    Path(args.out).write_text(html_doc, encoding="utf-8")
    print(f"Done: {args.out} ({len(html_doc)} chars)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
