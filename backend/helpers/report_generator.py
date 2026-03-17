"""
Report generator module.

Provides the HTML template and data-assembly logic used by both:
  - scripts/gen_report.py (CLI batch report)
  - backend/routes/oss_routes_stage4.py (single-issue API endpoint)
"""

import json
import os
from datetime import datetime, timedelta
from glob import glob


CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache")

# ---------------------------------------------------------------------------
# HTML template (self-contained with CSS + JS, uses __JSON_BLOB__ placeholder)
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pipeline Report</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --surface2: #1c2129; --border: #30363d;
  --text: #e6edf3; --text2: #c9d1d9; --muted: #8b949e;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; --blue: #58a6ff;
  --purple: #bc8cff; --orange: #db6d28; --cyan: #39d2c0;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { height: 100%; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100%; display: flex; flex-direction: column; align-items: center; }

/* Fluid column — fills iframe/popout width with small inset */
.shell { width: 92%; max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; height: 100vh; }

.header { padding: 10px 0 6px; display: flex; align-items: baseline; gap: 12px; flex-shrink: 0; }
.header h1 { font-size: 1.2em; font-weight: 600; }
.header .sub { color: var(--muted); font-size: 0.8em; }

.run-tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.run-tab { padding: 6px 20px; cursor: pointer; color: var(--muted); font-size: 0.82em; font-weight: 500; border-bottom: 2px solid transparent; transition: all 0.15s; user-select: none; }
.run-tab:hover { color: var(--text2); }
.run-tab.active { color: var(--blue); border-bottom-color: var(--blue); }
.run-tab .tag { font-size: 0.75em; color: var(--muted); margin-left: 6px; }

.content { flex: 1; overflow-y: auto; padding: 8px 0 16px; }

.stage-timeline { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.stage-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; position: relative; overflow: hidden; }
.stage-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; }
.stage-card.s1::before { background: var(--blue); }
.stage-card.s2::before { background: var(--purple); }
.stage-card.s3::before { background: var(--cyan); }
.stage-card .stage-label { font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 4px; font-weight: 600; }
.stage-card .stage-title { font-size: 0.95em; font-weight: 600; margin-bottom: 6px; }
.stage-card .stage-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 14px; }
.stage-card .sg-label { font-size: 0.75em; color: var(--muted); }
.stage-card .sg-value { font-size: 0.85em; font-weight: 500; }

/* Tooltips */
.tip { cursor: help; border-bottom: 1px dotted var(--muted); }
#tooltip { position: fixed; z-index: 9999; background: #1c2129; color: var(--text2); font-size: 0.8em; font-weight: 400; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); width: 260px; line-height: 1.4; pointer-events: none; opacity: 0; transition: opacity 0.12s; }

.section-header { font-size: 0.95em; font-weight: 600; margin: 12px 0 8px; padding-bottom: 4px; border-bottom: 1px solid var(--border); color: var(--text); display: flex; align-items: center; gap: 8px; }
.section-header .count { font-size: 0.75em; color: var(--muted); font-weight: 400; }

.summary-row { display: flex; gap: 8px; margin-bottom: 10px; }
.metric-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; }
.metric-card .mc-label { font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 1px; }
.metric-card .mc-value { font-size: 1.2em; font-weight: 700; }
.metric-card .mc-value.good { color: var(--green); }
.metric-card .mc-value.bad { color: var(--red); }
.metric-card .mc-value.warn { color: var(--yellow); }
.metric-card .mc-value.info { color: var(--blue); }

.issue-pills { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.issue-pill { display: flex; align-items: center; gap: 6px; padding: 5px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; transition: all 0.15s; user-select: none; min-width: 0; }
.issue-pill:hover { border-color: rgba(88,166,255,0.4); background: var(--surface2); }
.issue-pill.active { border-color: var(--blue); background: rgba(88,166,255,0.08); }
.issue-pill .ip-num { font-weight: 700; color: var(--blue); font-size: 0.9em; white-space: nowrap; }
.issue-pill .ip-badges { display: flex; gap: 4px; }
.issue-pill .ip-time { color: var(--muted); font-size: 0.75em; white-space: nowrap; }

.detail-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.detail-panel-header { padding: 10px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; }
.detail-panel-header .dp-num { font-weight: 700; color: var(--blue); font-size: 1em; }
.detail-panel-header .dp-title { flex: 1; font-size: 0.85em; color: var(--text2); }
.detail-panel-header .dp-time { color: var(--muted); font-size: 0.82em; }
.detail-panel-body { padding: 12px 16px; }

.detail-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
@media (max-width: 900px) { .detail-grid { grid-template-columns: 1fr 1fr; } }
.detail-section-title { font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 6px; font-weight: 600; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
.d-row { display: flex; justify-content: space-between; font-size: 0.82em; padding: 3px 0; }
.d-row .label { color: var(--muted); }
.d-row .val { font-weight: 500; }

.timing-section { margin-bottom: 10px; }
.timing-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 6px 0; background: var(--border); }
.timing-bar .tb-seg { height: 100%; }
.timing-bar .tb-swe { background: var(--blue); }
.timing-bar .tb-sa { background: var(--purple); }
.timing-bar .tb-rev { background: var(--yellow); }
.timing-bar .tb-rem { background: var(--cyan); }
.timing-legend { display: flex; gap: 14px; font-size: 0.75em; color: var(--muted); flex-wrap: wrap; }
.timing-legend span { display: flex; align-items: center; gap: 4px; }
.timing-legend span::before { content: ''; display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.timing-legend .tl-swe::before { background: var(--blue); }
.timing-legend .tl-sa::before { background: var(--purple); }
.timing-legend .tl-rev::before { background: var(--yellow); }
.timing-legend .tl-rem::before { background: var(--cyan); }
.timing-stamps { display: flex; gap: 14px; font-size: 0.75em; color: var(--muted); margin-top: 4px; flex-wrap: wrap; }

.tools-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.tool-tag { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 2px 8px; font-size: 0.78em; font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace; color: var(--text2); }

.b { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.72em; font-weight: 600; white-space: nowrap; }
.b-green { background: rgba(63,185,80,0.15); color: var(--green); }
.b-red { background: rgba(248,81,73,0.15); color: var(--red); }
.b-yellow { background: rgba(210,153,34,0.15); color: var(--yellow); }
.b-blue { background: rgba(88,166,255,0.15); color: var(--blue); }
.b-purple { background: rgba(188,140,255,0.15); color: var(--purple); }
.b-muted { background: rgba(139,148,158,0.1); color: var(--muted); }

.empty-detail { padding: 48px; text-align: center; color: var(--muted); font-size: 0.9em; }

.sa-findings { margin-top: 6px; border-top: 1px solid var(--border); padding-top: 6px; }
.sa-finding { display: flex; gap: 8px; font-size: 0.78em; padding: 2px 0; align-items: baseline; }
.sf-file { color: var(--blue); font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace; font-size: 0.85em; white-space: nowrap; flex-shrink: 0; }
.sf-msg { color: var(--text2); }

details { margin-top: 16px; }
details summary { cursor: pointer; color: var(--blue); font-size: 0.82em; font-weight: 500; }
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 14px; overflow-x: auto; font-size: 0.75em; margin-top: 8px; color: var(--text2); line-height: 1.5; max-height: 300px; overflow-y: auto; }
</style>
</head>
<body>
<div class="shell">

<div class="header">
  <h1>Pipeline Report</h1>
  <div class="sub" id="headerSub"></div>
</div>

<div class="run-tabs" id="runTabs"></div>

<div class="content" id="app"></div>

</div>

<script>
const DATA = __JSON_BLOB__;
let activeRun = Math.max(0, DATA.runs.length - 1);
let activeIssue = 0;

function badge(text, cls) { return `<span class="b b-${cls}">${text}</span>`; }
function yn(v) { return v ? `<span class="b b-green">YES</span>` : `<span class="b b-muted">no</span>`; }
function fmtMin(ms) { return ms > 0 ? (ms / 60000).toFixed(1) + 'm' : '\u2014'; }
function fmtTime(iso) { if (!iso) return '\u2014'; const d = new Date(iso); return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); }
function pct(part, total) { return total > 0 ? Math.round(part / total * 100) : 0; }
function tip(label, explanation) { return `<span class="tip" data-tip="${explanation.replace(/"/g,'&quot;')}">${label}</span>`; }

// Global tooltip element
const _tip = document.createElement('div');
_tip.id = 'tooltip';
document.body.appendChild(_tip);
document.addEventListener('mouseover', e => {
  const el = e.target.closest('.tip');
  if (!el) { _tip.style.opacity = '0'; return; }
  _tip.textContent = el.dataset.tip;
  _tip.style.opacity = '1';
  const r = el.getBoundingClientRect();
  const tw = 260;
  let left = r.left + r.width / 2 - tw / 2;
  if (left < 8) left = 8;
  if (left + tw > window.innerWidth - 8) left = window.innerWidth - tw - 8;
  _tip.style.left = left + 'px';
  _tip.style.top = (r.top - _tip.offsetHeight - 6) + 'px';
  if (r.top - _tip.offsetHeight - 6 < 4) {
    _tip.style.top = (r.bottom + 6) + 'px';
  }
});
document.addEventListener('mouseout', e => {
  if (e.target.closest('.tip')) _tip.style.opacity = '0';
});

function renderTabs() {
  document.getElementById('runTabs').innerHTML = DATA.runs.map((r, i) =>
    `<div class="run-tab ${i === activeRun ? 'active' : ''}" onclick="switchRun(${i})">${r.label}<span class="tag">${r.tag}</span></div>`
  ).join('');
}

function switchRun(i) {
  activeRun = i;
  activeIssue = 0;
  renderTabs();
  renderContent();
}

function selectIssue(i) {
  activeIssue = i;
  renderPills();
  renderDetail();
}

function renderPills() {
  const entries = DATA.runs[activeRun].entries;
  document.getElementById('issuePills').innerHTML = entries.map((e, i) => {
    const wf = e.workflow || {};
    const timing = e.timing || {};
    const reproBadge = wf.reproduced ? badge('Repro','green') : wf.step_count ? badge('No Repro','muted') : '';
    const verifyBadge = wf.verified ? badge('Verified','green') : wf.step_count ? badge('Unverified','muted') : '';
    let totalMin = '';
    if (timing.assigned_at && timing.completed_at) {
      totalMin = fmtMin(new Date(timing.completed_at) - new Date(timing.assigned_at));
    }
    return `<div class="issue-pill ${i === activeIssue ? 'active' : ''}" onclick="selectIssue(${i})">
      <span class="ip-num">#${e.issue_number}</span>
      <span class="ip-badges">${reproBadge}${verifyBadge}</span>
      ${totalMin ? `<span class="ip-time">${totalMin}</span>` : ''}
    </div>`;
  }).join('');
}

function renderDetail() {
  const entries = DATA.runs[activeRun].entries;
  const panel = document.getElementById('detailPanel');
  if (!entries.length) { panel.innerHTML = '<div class="empty-detail">No issues in this run.</div>'; return; }

  const e = entries[activeIssue];
  const swe = e.swe || {};
  const sa = e.static_analysis || {};
  const rev = e.review || {};
  const rem = e.remediation || {};
  const wf = e.workflow || {};
  const timing = e.timing || {};

  const saBadge = sa.conclusion === 'success' ? badge('SA Pass','green') : sa.conclusion === 'failure' ? badge('SA Fail','red') : badge('SA ?','yellow');
  const remBadge = rem.skipped ? badge('Skipped','yellow') : badge('+' + (rem.new_commits||0) + ' commits','blue');

  let totalMin = '\u2014';
  if (timing.assigned_at && timing.completed_at) {
    totalMin = fmtMin(new Date(timing.completed_at) - new Date(timing.assigned_at));
  }

  let timingHtml = '';
  if (timing.assigned_at && timing.completed_at) {
    const t0 = new Date(timing.assigned_at).getTime();
    const tEnd = new Date(timing.completed_at).getTime();
    const total = tEnd - t0;
    if (total > 0) {
      const tSwe = timing.swe_done_at ? new Date(timing.swe_done_at).getTime() : t0;
      const tSa = timing.sa_done_at ? new Date(timing.sa_done_at).getTime() : tSwe;
      const tRev = timing.review_done_at ? new Date(timing.review_done_at).getTime() : tSa;
      const tRem = timing.remediation_done_at ? new Date(timing.remediation_done_at).getTime() : tRev;

      timingHtml = `<div class="timing-section">
        <div class="timing-legend">
          <span class="tl-swe">SWE ${fmtMin(tSwe - t0)}</span>
          <span class="tl-sa">SA ${fmtMin(tSa - tSwe)}</span>
          <span class="tl-rev">Review ${fmtMin(tRev - tSa)}</span>
          <span class="tl-rem">Remediation ${fmtMin(tRem - tRev)}</span>
        </div>
        <div class="timing-bar">
          <div class="tb-seg tb-swe" style="width:${pct(tSwe-t0,total)}%"></div>
          <div class="tb-seg tb-sa" style="width:${pct(tSa-tSwe,total)}%"></div>
          <div class="tb-seg tb-rev" style="width:${pct(tRev-tSa,total)}%"></div>
          <div class="tb-seg tb-rem" style="width:${pct(tRem-tRev,total)}%"></div>
        </div>
        <div class="timing-stamps">
          <span>Assigned ${fmtTime(timing.assigned_at)}</span>
          <span>SWE ${fmtTime(timing.swe_done_at)}</span>
          <span>SA ${fmtTime(timing.sa_done_at)}</span>
          <span>Review ${fmtTime(timing.review_done_at)}</span>
          <span>Done ${fmtTime(timing.completed_at)}</span>
        </div>
      </div>`;
    }
  }

  const tools = (wf.tools_used || []).filter(t => t && !t.startsWith('"') && !t.startsWith("'") && t !== 'if' && t !== 'all');

  panel.innerHTML = `
    <div class="detail-panel-header">
      <span class="dp-num">#${e.issue_number}</span>
      <span class="dp-title">PR #${swe.pr_number || '?'} \u2014 ${swe.title || 'Untitled'}</span>
      <span class="dp-time">${totalMin}</span>
    </div>
    <div class="detail-panel-body">
      ${timingHtml}
      <div class="detail-grid">
        <div class="detail-section">
          <div class="detail-section-title">SWE Agent Output</div>
          <div class="d-row"><span class="label">Branch</span><span class="val" style="font-family:monospace;font-size:0.8em">${swe.pr_branch || '\u2014'}</span></div>
          <div class="d-row"><span class="label">Diff</span><span class="val"><span style="color:var(--green)">+${swe.additions||0}</span> / <span style="color:var(--red)">-${swe.deletions||0}</span></span></div>
          <div class="d-row"><span class="label">Files Changed</span><span class="val">${swe.changed_files||0}</span></div>
          <div class="d-row"><span class="label">Commits</span><span class="val">${swe.commit_count||0}</span></div>
        </div>
        <div class="detail-section">
          <div class="detail-section-title">Static Analysis ${saBadge}</div>
          ${(sa.jobs || []).length ? sa.jobs.map(j => {
            const jb = j.conclusion === 'success' ? badge('pass','green') : j.conclusion === 'failure' ? badge('fail','red') : badge(j.conclusion||'?','yellow');
            const count = (j.annotations || []).length;
            return `<div class="d-row"><span class="label" style="font-weight:600">${j.name}</span><span class="val">${jb}${count ? ' <span style=\"color:var(--muted);font-size:0.8em\">' + count + ' finding' + (count>1?'s':'') + '</span>' : ''}</span></div>`;
          }).join('') : `<div class="d-row"><span class="label">Run</span><span class="val" style="font-family:monospace;font-size:0.8em">${sa.run_id || '\u2014'}</span></div>`}
          ${(sa.jobs || []).some(j => j.annotations?.length) ? '<div class="sa-findings">' + sa.jobs.filter(j => j.annotations?.length).map(j =>
            j.annotations.map(a =>
              `<div class="sa-finding"><span class="sf-file">${a.path}:${a.line}</span><span class="sf-msg">${a.message.split('\\n')[0]}</span></div>`
            ).join('')
          ).join('') + '</div>' : ''}
        </div>
        <div class="detail-section">
          <div class="detail-section-title">Code Review</div>
          <div class="d-row"><span class="label">Inline Comments</span><span class="val">${rev.inline_comment_count||0}</span></div>
          <div class="d-row"><span class="label">Actionable</span><span class="val">${yn(rev.actionable)}</span></div>
        </div>
        <div class="detail-section">
          <div class="detail-section-title">Remediation</div>
          <div class="d-row"><span class="label">Status</span><span class="val">${remBadge}</span></div>
          <div class="d-row"><span class="label">New Commits</span><span class="val">${rem.new_commits||0}</span></div>
          ${rem.additions != null ? `<div class="d-row"><span class="label">Post-Fix Diff</span><span class="val"><span style="color:var(--green)">+${rem.additions||0}</span> / <span style="color:var(--red)">-${rem.deletions||0}</span></span></div>` : ''}
          ${rem.changed_files != null ? `<div class="d-row"><span class="label">Files Changed</span><span class="val">${rem.changed_files}</span></div>` : ''}
        </div>
        <div class="detail-section">
          <div class="detail-section-title">Workflow Compliance</div>
          <div class="d-row"><span class="label">${tip('Reproduced', 'Agent ran tests or lint before making any edits, confirming the bug exists first.')}</span><span class="val">${yn(wf.reproduced)}</span></div>
          <div class="d-row"><span class="label">${tip('Verified', 'Agent ran tests or lint after edits to confirm the fix actually works.')}</span><span class="val">${yn(wf.verified)}</span></div>
          <div class="d-row"><span class="label">${tip('Self-Corrected', 'Agent revised its code after receiving code review feedback.')}</span><span class="val">${yn(wf.self_corrected)}</span></div>
          <div class="d-row"><span class="label">${tip('CodeQL', 'Agent ran or triggered CodeQL security/quality analysis.')}</span><span class="val">${yn(wf.codeql)}</span></div>
          <div class="d-row"><span class="label">${tip('Code Review', 'Agent performed a self-review of its own changes before finishing.')}</span><span class="val">${yn(wf.code_review)}</span></div>
          <div class="d-row"><span class="label">Tool Installed</span><span class="val">${yn(wf.tool_installed)}</span></div>
          <div class="d-row"><span class="label">Steps</span><span class="val">${wf.step_count || '\u2014'}</span></div>
        </div>
        <div class="detail-section">
          <div class="detail-section-title">Tools Used</div>
          <div class="tools-list">${tools.length ? tools.map(t => `<span class="tool-tag">${t}</span>`).join('') : '<span style="color:var(--muted);font-size:0.82em">No tools detected</span>'}</div>
        </div>
      </div>
      <details><summary>Raw retrospective JSON</summary><pre>${JSON.stringify(e, null, 2)}</pre></details>
    </div>`;
}

function renderContent() {
  const run = DATA.runs[activeRun];
  if (!run) {
    document.getElementById('headerSub').textContent = `${DATA.repo} \u00b7 No retrospective data yet`;
    document.getElementById('app').innerHTML = '<div class="empty-detail">No retrospective logs found for this issue. The pipeline may still be in progress.</div>';
    return;
  }
  const entries = run.entries;
  const n = entries.length;
  const h = DATA.health;

  document.getElementById('headerSub').textContent =
    `${DATA.repo} \u00b7 ${n} issues \u00b7 ${run.tag}`;

  let html = '';

  // Stage 1/2/3 timeline cards
  html += '<div class="stage-timeline">';

  // Stage 1: Target Repo
  html += `<div class="stage-card s1">
    <div class="stage-label">Stage 1 \u2014 Target Repo</div>
    <div class="stage-title">${DATA.repo}</div>
    <div class="stage-grid">
      <div><div class="sg-label">Language</div><div class="sg-value">${h.language || '\u2014'}</div></div>
      <div><div class="sg-label">Default Branch</div><div class="sg-value">${h.defaultBranch}</div></div>
      <div><div class="sg-label">${tip('Viability', 'Overall likelihood a PR to this repo will be reviewed and merged. Composite of maintainer health, merge accessibility, and availability.')}</div><div class="sg-value">${h.overallViability}%</div></div>
      <div><div class="sg-label">${tip('Availability', 'How many open issues are available for contribution. Higher = more opportunities to pick from.')}</div><div class="sg-value">${h.availabilityScore}%</div></div>
      <div><div class="sg-label">${tip('Maintainer', 'How active and responsive the maintainers are. Based on recent commit activity, issue response times, and PR review frequency.')}</div><div class="sg-value">${h.maintainerHealthScore}%</div></div>
      <div><div class="sg-label">${tip('Merge Access', 'How accessible the merge process is for external contributors. Based on external contributor merge rate, rejection reasons, and PR patterns.')}</div><div class="sg-value">${h.mergeAccessibilityScore}%</div></div>
      <div><div class="sg-label">Merge Style</div><div class="sg-value">${h.prPatterns?.mergeStyle || '\u2014'}</div></div>
      <div><div class="sg-label">Median TTM</div><div class="sg-value">${h.prPatterns?.medianTimeToMergeDays || '\u2014'}d</div></div>
    </div>
  </div>`;

  // Stage 2: Scored Issues
  const sample = entries[0] || {};
  const dq = sample.data_quality || {};
  const dc = dq.dossier_completeness || {};
  const tierColor = dq.context_tier === 1 ? 'green' : dq.context_tier === 2 ? 'yellow' : 'red';
  const tierLabel = dq.context_tier === 1 ? 'Tier 1 \u2014 Issue Brief' : dq.context_tier === 2 ? 'Tier 2 \u2014 Dossier Only' : 'Tier 3 \u2014 Fallback';
  const dossierScore = (dc.score != null ? dc.score : '?') + '/' + (dc.total != null ? dc.total : '6');
  const ck = (v) => v ? '\u2705' : '\u274c';
  html += `<div class="stage-card s2">
    <div class="stage-label">Stage 2 \u2014 Scored Issues</div>
    <div class="stage-title">${n} Issues Selected</div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      ${badge(tip(tierLabel, 'Quality tier of context given to the agent. Tier 1 = full aggregator issue brief (best). Tier 2 = dossier sections only. Tier 3 = CONTRIBUTING.md fallback via gh CLI.'), tierColor)}
    </div>
    <div class="stage-grid">
      <div><div class="sg-label">Overview</div><div class="sg-value">${ck(dc.overview)}</div></div>
      <div><div class="sg-label">Issue Board</div><div class="sg-value">${ck(dc.issueBoard)}</div></div>
      <div><div class="sg-label">Contrib Rules</div><div class="sg-value">${ck(dc.contributionRules)}</div></div>
      <div><div class="sg-label">Anti-Patterns</div><div class="sg-value">${ck(dc.antiPatterns)}</div></div>
      <div><div class="sg-label">Env Setup</div><div class="sg-value">${ck(dc.environmentSetup)}</div></div>
      <div><div class="sg-label">Success Pat.</div><div class="sg-value">${ck(dc.successPatterns)}</div></div>
    </div>
  </div>`;

  // Stage 3: Fork & Assign
  const firstTiming = (entries[0]?.timing || {});
  const assignStart = firstTiming.assigned_at ? new Date(firstTiming.assigned_at).toLocaleTimeString() : '\u2014';
  const firstLang = entries[0]?.pipeline?.language;
  const shortName = (s) => {
    if (!s) return '\u2014';
    return s.replace('CopilotSWEDispatcher','Copilot SWE').replace('CopilotReviewDispatcher','Copilot Review').replace('CopilotRemediationDispatcher','Copilot Remed.').replace('GitHubActionsDispatcher','GH Actions');
  };
  html += `<div class="stage-card s3">
    <div class="stage-label">Stage 3 \u2014 Fork & Assign</div>
    <div class="stage-title">Copilot SWE Agent</div>
    <div class="stage-grid">
      <div><div class="sg-label">Language</div><div class="sg-value" style="color:${firstLang ? 'var(--green)' : 'var(--red)'}">${firstLang || 'null'}</div></div>
      <div><div class="sg-label">Assigned At</div><div class="sg-value">${assignStart}</div></div>
      <div><div class="sg-label">SWE</div><div class="sg-value">${shortName(entries[0]?.pipeline?.swe_agent)}</div></div>
      <div><div class="sg-label">Review</div><div class="sg-value">${shortName(entries[0]?.pipeline?.review_agent)}</div></div>
      <div><div class="sg-label">SA</div><div class="sg-value">${shortName(entries[0]?.pipeline?.static_analysis)}</div></div>
      <div><div class="sg-label">Remediation</div><div class="sg-value">${shortName(entries[0]?.pipeline?.remediation_agent)}</div></div>
    </div>
  </div>`;

  html += '</div>';

  // Run summary
  html += '<div class="section-header">Stage 4 Overview <span class="count">' + n + ' issues</span></div>';

  const avgSteps = entries.reduce((s,e) => s + (e.workflow?.step_count||0), 0) / n;
  const reproduced = entries.filter(e => e.workflow?.reproduced).length;
  const verified = entries.filter(e => e.workflow?.verified).length;
  const hasWf = entries.filter(e => e.workflow?.step_count).length;

  let totalMs = 0, timeCount = 0;
  for (const e of entries) {
    const t = e.timing || {};
    if (t.assigned_at && t.completed_at) { totalMs += new Date(t.completed_at) - new Date(t.assigned_at); timeCount++; }
  }
  const avgTime = timeCount > 0 ? fmtMin(totalMs / timeCount) : '\u2014';

  html += '<div class="summary-row">';
  html += `<div class="metric-card"><div class="mc-label">Avg Steps</div><div class="mc-value info">${avgSteps.toFixed(0)}</div></div>`;
  html += `<div class="metric-card"><div class="mc-label">Reproduced</div><div class="mc-value ${reproduced >= n*0.6 ? 'good' : 'warn'}">${reproduced}/${n}</div></div>`;
  html += `<div class="metric-card"><div class="mc-label">Verified</div><div class="mc-value ${verified >= n*0.4 ? 'good' : 'warn'}">${verified}/${n}</div></div>`;
  html += `<div class="metric-card"><div class="mc-label">Avg Time</div><div class="mc-value info">${avgTime}</div></div>`;
  html += '</div>';

  if (hasWf < n) {
    html += `<div style="background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.2);border-radius:6px;padding:6px 10px;margin-bottom:6px;font-size:0.78em;color:var(--red);flex-shrink:0">Workflow data missing for ${n - hasWf} of ${n} issues.</div>`;
  }

  // Issue selector pills + detail panel
  html += '<div class="section-header">Issue Details</div>';
  html += '<div id="issuePills" class="issue-pills"></div>';
  html += '<div id="detailPanel" class="detail-panel"></div>';

  document.getElementById('app').innerHTML = html;
  renderPills();
  renderDetail();
}

renderTabs();
renderContent();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Data assembly helpers (shared between CLI and API)
# ---------------------------------------------------------------------------

def cluster_runs(entries):
    """Cluster retrospective entries into runs by >1hr time gaps."""
    sorted_entries = sorted(entries, key=lambda e: e.get("created_at", ""))
    runs = []
    current_run = []
    for entry in sorted_entries:
        ts = entry.get("created_at", "")
        if not ts:
            current_run.append(entry)
            continue
        if current_run:
            prev_ts = current_run[-1].get("created_at", "")
            if prev_ts:
                try:
                    t_prev = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                    t_curr = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if (t_curr - t_prev) > timedelta(hours=1):
                        runs.append(current_run)
                        current_run = []
                except ValueError:
                    pass
        current_run.append(entry)
    if current_run:
        runs.append(current_run)

    run_defs = []
    for i, run_entries in enumerate(runs):
        first_ts = run_entries[0].get("created_at", "")
        try:
            dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            tag = dt.strftime("%b %d, %H:%M")
        except (ValueError, TypeError):
            tag = "?"
        run_defs.append({
            "label": f"Run {i + 1}",
            "tag": tag,
            "entries": run_entries,
        })
    return run_defs


def load_health_from_cache(repo_name):
    """Find health data in the file-based cache."""
    for cache_file in glob(os.path.join(CACHE_DIR, "*.json")):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("key") != "oss-stage1-targets":
                continue
            targets = d.get("data", {}).get("targets", [])
            for t in targets:
                slug = t.get("slug", "")
                if slug.endswith(f"-{repo_name}") or slug == repo_name:
                    return t.get("health", {})
        except (json.JSONDecodeError, KeyError):
            continue
    return {}


def build_health_data(assignments, cached_health):
    """Build the health data dict from assignments + cached health."""
    language = None
    default_branch = None
    for a in assignments:
        if not language and a.get("language"):
            language = a["language"]
        if not default_branch and a.get("default_branch"):
            default_branch = a["default_branch"]
        if language and default_branch:
            break

    return {
        "language": language,
        "defaultBranch": default_branch or "main",
        "maintainerHealthScore": cached_health.get("maintainerHealthScore", 0),
        "mergeAccessibilityScore": cached_health.get("mergeAccessibilityScore", 0),
        "availabilityScore": cached_health.get("availabilityScore", 0),
        "overallViability": cached_health.get("overallViability", 0),
        "prPatterns": cached_health.get("prPatterns", {}),
    }


def derive_slugs(assignments):
    """Derive fork_slug and origin_slug from assignment data."""
    fork_slug = None
    origin_slug = None
    for a in assignments:
        if not origin_slug and a.get("origin_slug"):
            origin_slug = a["origin_slug"]
        if not fork_slug:
            url = a.get("fork_issue_url", "")
            if "github.com/" in url:
                parts = url.split("github.com/")[1].split("/")
                if len(parts) >= 2:
                    fork_slug = f"{parts[0]}/{parts[1]}"
        if fork_slug and origin_slug:
            break
    return fork_slug, origin_slug


def build_report_data(repo_name, logs, assignments, cached_health=None):
    """Assemble the report_data dict for template substitution.

    Args:
        repo_name: Short repo name (e.g. "email-verifier").
        logs: Retrospective log entries for this repo.
        assignments: Assignment records for this repo.
        cached_health: Optional pre-loaded health data dict.

    Returns:
        dict suitable for JSON serialization into the HTML template.
    """
    if cached_health is None:
        cached_health = load_health_from_cache(repo_name)

    _, origin_slug = derive_slugs(assignments)
    if not origin_slug:
        origin_slug = repo_name

    run_defs = cluster_runs(logs)
    health_data = build_health_data(assignments, cached_health)

    return {
        "repo": origin_slug,
        "health": health_data,
        "assignments": assignments,
        "runs": run_defs,
    }


def render_report_html(report_data):
    """Substitute report_data into the HTML template and return the string."""
    json_blob = json.dumps(report_data)
    return HTML_TEMPLATE.replace("__JSON_BLOB__", json_blob)


# ---------------------------------------------------------------------------
# API entry point (called from backend route)
# ---------------------------------------------------------------------------

def generate_issue_report_html(svc, repo, issue_number):
    """Generate a self-contained pipeline report HTML for a single issue.

    Args:
        svc: OSSService instance.
        repo: Short repo name (e.g. "email-verifier").
        issue_number: Upstream issue number.

    Returns:
        HTML string with embedded data for the matching issue.
    """
    all_logs = svc.get_retrospective_logs()
    all_assignments = svc.get_assigned_issues()

    repo_logs = [e for e in all_logs if e.get("repo") == repo]
    repo_assignments = [a for a in all_assignments if a.get("repo") == repo]

    issue_logs = [e for e in repo_logs if e.get("issue_number") == issue_number]
    if not issue_logs:
        issue_logs = repo_logs

    cached_health = load_health_from_cache(repo)
    report_data = build_report_data(repo, issue_logs, repo_assignments, cached_health)
    return render_report_html(report_data)
