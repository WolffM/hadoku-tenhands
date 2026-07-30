/**
 * PRReviewPanel — the merge gate.
 *
 * The pipeline stops at "pull request open" on purpose: merging is the one
 * step a human owns. This panel is that step, and the reason it lives here
 * instead of being a link to GitHub is the pairing — each PR is shown next to
 * the task it came from, so the plan that was approved sits beside the diff it
 * produced. GitHub cannot show that, because it has never heard of the board.
 *
 * Merge is offered only when GitHub says it would actually succeed. A button
 * that reliably fails teaches people to ignore buttons.
 *
 * The exception is a PR whose checks are still running. Refusing that one means
 * coming back later to press the same button, so it offers "Merge when green"
 * instead: GitHub records the decision now and performs the merge on a green
 * run, leaving the PR open if the run fails. That keeps the human gate — a
 * person still decides — without making them wait on CI.
 */

import { Badge, type BadgeVariant, EmptyState, SectionHeader } from '../common'
import type { TaskAutoPR } from '../../api/types'

const CHECK_VARIANT: Record<TaskAutoPR['checks'], BadgeVariant> = {
  passing: 'success',
  failing: 'danger',
  pending: 'info',
  none: 'secondary'
}

/** What the button should do for one PR, or null if it can't act at all. */
function mergeAction(pr: TaskAutoPR): { label: string; auto: boolean } | null {
  // Conflicts, red runs and drafts are all "not until something changes".
  if (pr.isDraft || pr.mergeState === 'DIRTY' || pr.checks === 'failing') return null
  // Still running: schedule it. `mergeState` is BLOCKED while a required check
  // is pending, so this case cannot be recognised from mergeState alone.
  if (pr.checks === 'pending') return { label: 'Merge when green', auto: true }
  if (pr.mergeState === 'CLEAN') return { label: 'Merge', auto: false }
  return null
}

interface PRReviewPanelProps {
  prs: TaskAutoPR[]
  /** `repo#number` of the PR mid-merge, or null. */
  merging: string | null
  mergeError: string | null
  onMerge: (repo: string, number: number, auto: boolean) => void
}

export function PRReviewPanel({ prs, merging, mergeError, onMerge }: PRReviewPanelProps) {
  return (
    <section className="taskauto-section" data-testid="taskauto-prs">
      <SectionHeader icon="🔀" title="PRs awaiting you" count={prs.length} />

      {mergeError && <p className="taskauto-error">{mergeError}</p>}

      {prs.length === 0 ? (
        <EmptyState
          icon="✅"
          title="Nothing waiting on a merge"
          description="Approved tasks become pull requests here once an agent implements them."
        />
      ) : (
        <div className="taskauto-prs">
          {prs.map(pr => {
            const id = `${pr.repo}#${pr.number}`
            const action = mergeAction(pr)
            const busy = merging === id
            return (
              <article key={id} className="taskauto-pr" data-testid={`taskauto-pr-${pr.number}`}>
                <header className="taskauto-pr__head">
                  <a className="taskauto-pr__title" href={pr.url} target="_blank" rel="noreferrer">
                    {pr.repo.split('/')[1]} #{pr.number} — {pr.title}
                  </a>
                  <Badge variant={CHECK_VARIANT[pr.checks]}>{pr.checks}</Badge>
                </header>

                <div className="taskauto-pr__meta">
                  <span className="taskauto-pr__diff">
                    +{pr.additions} / −{pr.deletions}
                  </span>
                  <span>
                    {pr.changedFiles} file{pr.changedFiles === 1 ? '' : 's'}
                  </span>
                  <code className="taskauto-pr__branch">{pr.branch}</code>
                  {pr.isDraft && <Badge variant="secondary">draft</Badge>}
                </div>

                <div className="taskauto-pr__actions">
                  <a
                    className="btn btn--secondary btn--sm"
                    href={`${pr.url}/files`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Review diff
                  </a>
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    disabled={!action || busy}
                    title={
                      action
                        ? action.auto
                          ? 'Squash-merge as soon as checks pass; stays open if they fail'
                          : 'Squash-merge and delete the branch'
                        : `Not mergeable: ${pr.isDraft ? 'draft' : pr.mergeState}`
                    }
                    onClick={() => action && onMerge(pr.repo, pr.number, action.auto)}
                  >
                    {busy ? 'Merging…' : (action?.label ?? 'Merge')}
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
