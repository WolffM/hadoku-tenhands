/**
 * OSSIssueList — Stage 2 placeholder
 *
 * Shows CVS-scored issues from target repos.
 * Stub for M1; aggregator integration coming in M2.
 */

import { EmptyState } from '../common/EmptyState'

export function OSSIssueList() {
  return (
    <div className="stage-panel">
      <EmptyState
        icon="\u{1F4CB}"
        title="Scored Issues"
        description="Aggregator integration coming in M2. This stage will show CVS-scored issues from target repos."
      />
    </div>
  )
}
