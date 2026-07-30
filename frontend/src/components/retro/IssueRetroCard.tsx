/**
 * IssueRetroCard — expandable card showing the full retrospective for one issue.
 *
 * Sections (all visible in a single holistic view when expanded):
 *   - Header: repo, issue, stage reached, context tier, upstream PR outcome
 *   - Timeline: step-by-step with timestamps and deltas
 *   - Human comments (open by default, most important signal)
 *   - Copilot workflow metrics
 *   - SA findings
 *   - Links to context brief and upstream PR body (open in side panel)
 */

import React, { useState, useEffect } from 'react'
import type { BatchIssue, PrComment, PrCommit, UpstreamIssueMention } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { getRetroPRCommits } from '../../api/endpoints'
import { ContextPanel } from './ContextPanel'

const BOT_LOGINS = new Set([
  'copilot-swe-agent',
  'app/copilot-swe-agent',
  'copilot',
  'github-actions[bot]',
  'dependabot[bot]',
  'coderabbitai[bot]',
  'renovate[bot]',
  'codecov[bot]',
  'snyk-bot',
  'vercel[bot]',
  'netlify[bot]',
  'sonarqubebot',
  'deepsource-autofix[bot]',
  'stale[bot]',
  'allcontributors[bot]',
  'imgbot[bot]',
  'whitesource-bolt-for-github[bot]'
])

function isBot(login: string): boolean {
  if (!login) return false
  const lower = login.toLowerCase()
  return BOT_LOGINS.has(lower) || lower.endsWith('[bot]')
}

function filterHuman(comments: PrComment[]): PrComment[] {
  return comments.filter(c => !isBot(c.author))
}

interface Props {
  item: BatchIssue
}

export function IssueRetroCard({ item }: Props) {
  const { assignment, upstream_pr, retro } = item
  const [expanded, setExpanded] = useState(false)
  const [contextPanel, setContextPanel] = useState<{ title: string; body: string } | null>(null)
  const [postCommits, setPostCommits] = useState<PrCommit[]>([])

  useEffect(() => {
    if (!expanded || !upstream_pr?.pr_number) return
    getRetroPRCommits(assignment.origin_slug, upstream_pr.pr_number, upstream_pr.submitted_at)
      .then(res => {
        if (res.success) setPostCommits(res.commits)
      })
      .catch(_err => {
        /* commit fetch is best-effort */
      })
  }, [expanded, assignment.origin_slug, upstream_pr?.pr_number, upstream_pr?.submitted_at])

  const humanForkComments = filterHuman(retro?.raw_comments?.fork_pr ?? [])
  const humanUpstreamComments = filterHuman(retro?.raw_comments?.upstream_pr ?? [])
  const totalHumanComments = humanForkComments.length + humanUpstreamComments.length
  const hasRetroData = !!(retro?.raw_comments || retro?.context_issue_body)

  // A `merged-in-fork-only` record has no PR number and no URL: the fix landed
  // in our fork and never went upstream. Treating that as "upstream-open" — the
  // old fallback for any unrecognised state — labelled it "Open upstream" and
  // rendered a `PR #` link pointing at nothing, which is the opposite of what
  // happened. Anything without a PR number is not an upstream PR.
  const hasUpstreamPR = !!(upstream_pr?.pr_url && upstream_pr.pr_number)

  const stageReached = hasUpstreamPR
    ? upstream_pr.state === 'merged'
      ? 'merged'
      : upstream_pr.state === 'closed'
        ? 'upstream-closed'
        : 'upstream-open'
    : upstream_pr
      ? 'fork-merged'
      : assignment.stage4_pr_number
        ? 'fork-pr'
        : 'dispatched'

  const stageLabel: Record<string, string> = {
    merged: 'Merged upstream',
    'upstream-closed': 'Closed upstream',
    'upstream-open': 'Open upstream',
    'fork-merged': 'Merged in fork only',
    'fork-pr': 'Fork PR created',
    dispatched: 'Dispatched'
  }

  const stageVariant: Record<string, string> = {
    merged: 'success',
    'upstream-closed': 'closed',
    'upstream-open': 'open',
    'fork-merged': 'neutral',
    'fork-pr': 'neutral',
    dispatched: 'neutral'
  }

  return (
    <div className={`retro-card ${expanded ? 'retro-card--expanded' : ''}`}>
      {/* Card header — always visible */}
      <button className="retro-card__header" onClick={() => setExpanded(v => !v)}>
        <div className="retro-card__title">
          <a
            href={`https://github.com/${assignment.origin_slug}/issues/${assignment.issue_number}`}
            target="_blank"
            rel="noreferrer"
            onClick={e => e.stopPropagation()}
            className="retro-card__repo-link"
          >
            {assignment.origin_slug}#{assignment.issue_number}
          </a>
          {hasUpstreamPR && (
            <>
              <span className="retro-card__sep">·</span>
              <a
                href={upstream_pr.pr_url}
                target="_blank"
                rel="noreferrer"
                onClick={e => e.stopPropagation()}
                className="retro-card__pr-link"
              >
                PR #{upstream_pr.pr_number}
              </a>
            </>
          )}
        </div>
        <div className="retro-card__badges">
          <span className={`retro-badge retro-badge--${stageVariant[stageReached]}`}>
            {stageLabel[stageReached]}
          </span>
          {assignment.context_tier && (
            <span className="retro-badge retro-badge--neutral">tier {assignment.context_tier}</span>
          )}
          {totalHumanComments > 0 && (
            <span className="retro-badge retro-badge--comments">
              💬 {totalHumanComments} human comment{totalHumanComments !== 1 ? 's' : ''}
            </span>
          )}
          <span className="retro-card__chevron">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="retro-card__body">
          {/* Timeline */}
          <RetroSection title="Timeline">
            <Timeline
              assignment={assignment}
              upstream_pr={upstream_pr}
              retro={retro}
              postCommits={postCommits}
            />
          </RetroSection>

          {/* Human comments — most important, shown prominently */}
          <RetroSection title={`Human comments (${totalHumanComments})`} accent defaultOpen>
            {totalHumanComments === 0 ? (
              <p className="retro-empty-section">
                {hasRetroData ? 'No human comments on this PR.' : 'Comment data unavailable.'}
              </p>
            ) : (
              <>
                {humanForkComments.length > 0 && (
                  <CommentThread comments={humanForkComments} label="Fork PR" />
                )}
                {humanUpstreamComments.length > 0 && (
                  <CommentThread comments={humanUpstreamComments} label="Upstream PR" />
                )}
              </>
            )}
          </RetroSection>

          {/* Copilot workflow */}
          {retro?.workflow && (
            <RetroSection title="Copilot workflow">
              <WorkflowMetrics workflow={retro.workflow} />
            </RetroSection>
          )}

          {/* SA findings */}
          {retro?.static_analysis?.jobs && retro.static_analysis.jobs.length > 0 && (
            <RetroSection title={`SA findings (${retro.static_analysis.conclusion ?? 'unknown'})`}>
              <SAFindings jobs={retro.static_analysis.jobs} />
            </RetroSection>
          )}

          {/* Cross-reference leaks */}
          {retro?.upstream_issue_mentions && retro.upstream_issue_mentions.length > 0 && (
            <RetroSection
              title={`Cross-reference leaks (${retro.upstream_issue_mentions.length})`}
              accent
            >
              <CrossRefLeaks mentions={retro.upstream_issue_mentions} />
            </RetroSection>
          )}

          {/* Context and PR body links */}
          <RetroSection title="Artifacts">
            <div className="retro-artifacts">
              {retro?.context_issue_body ? (
                <button
                  className="retro-artifact-link"
                  onClick={() =>
                    setContextPanel({
                      title: 'Context brief (fork issue)',
                      body: retro.context_issue_body!
                    })
                  }
                >
                  📄 Context brief (fork issue)
                </button>
              ) : (
                <span className="retro-artifact-missing">Context brief unavailable</span>
              )}
              {retro?.upstream_pr_body ? (
                <button
                  className="retro-artifact-link"
                  onClick={() =>
                    setContextPanel({ title: 'Upstream PR body', body: retro.upstream_pr_body! })
                  }
                >
                  📤 Upstream PR body
                </button>
              ) : (
                <span className="retro-artifact-missing">Upstream PR body unavailable</span>
              )}
            </div>
          </RetroSection>
        </div>
      )}

      {/* Side panel for context/PR body */}
      {contextPanel && (
        <ContextPanel
          title={contextPanel.title}
          body={contextPanel.body}
          onClose={() => setContextPanel(null)}
        />
      )}
    </div>
  )
}

// ---- Sub-components ----

function RetroSection({
  title,
  children,
  accent = false,
  defaultOpen = false
}: {
  title: string
  children: React.ReactNode
  accent?: boolean
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`retro-section ${accent ? 'retro-section--accent' : ''}`}>
      <button className="retro-section__toggle" onClick={() => setOpen(v => !v)}>
        <span>{open ? '▼' : '▶'}</span>
        <span className="retro-section__title">{title}</span>
      </button>
      {open && <div className="retro-section__body">{children}</div>}
    </div>
  )
}

function Timeline({
  assignment,
  upstream_pr,
  retro,
  postCommits
}: Pick<BatchIssue, 'assignment' | 'upstream_pr' | 'retro'> & { postCommits: PrCommit[] }) {
  const timing = retro?.timing
  const wentUpstream = !!(upstream_pr?.pr_url && upstream_pr.pr_number)
  const steps: { label: string; ts: string | null | undefined; variant?: string }[] = [
    // Pre-tracking records (everything before assignment tracking shipped)
    // carry only batch/repo/issue on the assignment, and keep the real
    // dispatch time in the retro's own timing block. Reading one source only
    // dropped the first step from every historical batch's timeline.
    { label: 'Dispatched', ts: assignment.assigned_at ?? timing?.assigned_at },
    { label: 'Fork PR created', ts: timing?.swe_done_at },
    {
      label: 'SA run',
      ts: timing?.sa_done_at,
      variant: retro?.static_analysis?.conclusion === 'failure' ? 'fail' : undefined
    },
    { label: 'Review', ts: timing?.review_done_at },
    { label: 'Remediation', ts: timing?.remediation_done_at },
    // A `merged-in-fork-only` record has the same shape as a submitted one —
    // submitted_at, merged_at — but no PR number, because the work landed in
    // our fork and never went upstream. Calling that "Upstream submitted"
    // followed by "Merged" describes a submission that never happened, and
    // for those records the two timestamps are the same moment anyway.
    ...(wentUpstream
      ? [
          { label: 'Upstream submitted', ts: upstream_pr?.submitted_at },
          ...(upstream_pr?.merged_at
            ? [{ label: 'Merged', ts: upstream_pr.merged_at, variant: 'success' }]
            : []),
          ...(upstream_pr?.closed_at && !upstream_pr.merged_at
            ? [{ label: 'Closed', ts: upstream_pr.closed_at, variant: 'closed' }]
            : [])
        ]
      : [
          {
            label: 'Fork PR merged',
            ts: upstream_pr?.merged_at ?? upstream_pr?.submitted_at
          }
        ])
  ]

  const filled = steps.filter(s => s.ts)
  if (filled.length === 0) return <p className="retro-empty-section">No timing data.</p>

  const allSteps: { label: string; ts: string; variant?: string; meta?: string }[] = filled.map(
    s => ({ label: s.label, ts: s.ts!, variant: s.variant })
  )
  for (const commit of postCommits) {
    allSteps.push({
      label: 'Commit',
      ts: commit.date,
      variant: 'commit',
      meta: `${commit.sha} — ${commit.message}`
    })
  }
  allSteps.sort((a, b) => a.ts.localeCompare(b.ts))

  return (
    <ol className="retro-timeline">
      {allSteps.map((step, i) => {
        const prev = allSteps[i - 1]
        const delta = prev?.ts && step.ts ? timeDelta(prev.ts, step.ts) : null
        return (
          <li
            key={`${step.label}-${i}`}
            className={`retro-timeline__step ${step.variant ? `retro-timeline__step--${step.variant}` : ''}`}
          >
            <span className="retro-timeline__dot" />
            <span className="retro-timeline__label">{step.label}</span>
            <span className="retro-timeline__ts">{formatDate(step.ts)}</span>
            {delta && <span className="retro-timeline__delta">(+{delta})</span>}
            {step.meta && <span className="retro-timeline__meta">{step.meta}</span>}
          </li>
        )
      })}
    </ol>
  )
}

function CommentThread({ comments, label }: { comments: PrComment[]; label: string }) {
  return (
    <div className="comment-thread">
      <div className="comment-thread__label">{label}</div>
      {comments.map((c, i) => (
        <div key={i} className={`comment ${c.comment_type === 'inline' ? 'comment--inline' : ''}`}>
          <div className="comment__meta">
            <span className="comment__author">@{c.author}</span>
            <span className="comment__time">{formatTimeAgo(c.created_at)}</span>
            {c.comment_type === 'inline' && c.path && (
              <span className="comment__location">
                {c.path}
                {c.line ? `:${c.line}` : ''}
              </span>
            )}
          </div>
          <div className="comment__body">{c.body}</div>
        </div>
      ))}
    </div>
  )
}

function WorkflowMetrics({ workflow }: { workflow: NonNullable<BatchIssue['retro']['workflow']> }) {
  const checks: { label: string; key: keyof typeof workflow; good: boolean }[] = [
    { label: 'Reproduced bug', key: 'reproduced', good: true },
    { label: 'Verified fix', key: 'verified', good: true },
    { label: 'Self-corrected', key: 'self_corrected', good: true },
    { label: 'Code review', key: 'code_review', good: true }
  ]
  return (
    <div className="workflow-metrics">
      <div className="workflow-metrics__chips">
        {checks.map(({ label, key }) =>
          workflow[key] !== undefined ? (
            <span
              key={key}
              className={`workflow-chip ${workflow[key] ? 'workflow-chip--yes' : 'workflow-chip--no'}`}
            >
              {workflow[key] ? '✓' : '✗'} {label}
            </span>
          ) : null
        )}
      </div>
      {workflow.step_count !== undefined && (
        <span className="workflow-metrics__meta">
          {workflow.step_count} steps
          {workflow.tools_used?.length ? ` · ${workflow.tools_used.join(', ')}` : ''}
        </span>
      )}
    </div>
  )
}

function SAFindings({
  jobs
}: {
  jobs: NonNullable<NonNullable<BatchIssue['retro']['static_analysis']>['jobs']>
}) {
  const findings = jobs.flatMap(job =>
    (job.annotations ?? []).map(a => ({ ...a, job: job.name, conclusion: job.conclusion }))
  )
  if (findings.length === 0) return <p className="retro-empty-section">No annotations.</p>
  return (
    <ul className="sa-findings">
      {findings.map((f, i) => (
        <li key={i} className={`sa-finding sa-finding--${f.level}`}>
          <span className="sa-finding__loc">
            {f.path}:{f.line}
          </span>
          <span className="sa-finding__msg">{f.message}</span>
        </li>
      ))}
    </ul>
  )
}

function CrossRefLeaks({ mentions }: { mentions: UpstreamIssueMention[] }) {
  return (
    <ul className="crossref-leaks">
      {mentions.map((m, i) => (
        <li key={i} className="crossref-leak">
          <span className="crossref-leak__actor">{m.actor}</span>
          {' referenced the upstream issue via '}
          <a href={m.source_url} target="_blank" rel="noreferrer" className="crossref-leak__link">
            {m.source_url.replace('https://github.com/', '')}
          </a>
          <span className="crossref-leak__date"> — {formatTimeAgo(m.created_at)}</span>
        </li>
      ))}
    </ul>
  )
}

// ---- Helpers ----

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function timeDelta(from: string, to: string): string {
  const ms = new Date(to).getTime() - new Date(from).getTime()
  if (ms < 0) return ''
  const mins = Math.round(ms / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.round(hrs / 24)}d`
}
