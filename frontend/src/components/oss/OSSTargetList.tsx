/**
 * OSSTargetList — Stage 1 placeholder
 *
 * Shows target repos with health scores.
 * Stub for M1; aggregator integration coming in M2.
 */

import { EmptyState } from '../common/EmptyState'

export function OSSTargetList() {
  return (
    <div className="stage-panel">
      <EmptyState
        icon="\u{1F3AF}"
        title="Target Repos"
        description="Aggregator integration coming in M2. This stage will show target repos with health scores."
      />
    </div>
  )
}
