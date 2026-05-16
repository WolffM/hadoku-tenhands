/**
 * StateBadge — color-coded badge for a crimson-kitty issue state.
 *
 * Three buckets, per operator request:
 *   success (green)  → the run completed: `replicated` (preview PR on the
 *                      fork), `submitted`, `merged`
 *   danger  (red)    → the run is dead: `aborted`, `closed_by_upstream`
 *   warning (yellow) → in progress, or parked waiting on the operator
 *                      (every other state, and anything `is_deferred`)
 *
 * A deferred run reports `current_state: "replicated"` but is NOT done — it
 * is waiting for an inbox decision — so `isDeferred` overrides to warning.
 */

import { Badge, type BadgeVariant } from '../common/Badge'

const COMPLETED = new Set(['replicated', 'submitted', 'merged'])
const DEAD = new Set(['aborted', 'closed_by_upstream'])

function variantFor(state: string, isDeferred?: boolean): BadgeVariant {
  if (isDeferred) return 'warning' // waiting on the operator, not finished
  if (DEAD.has(state)) return 'danger'
  if (COMPLETED.has(state)) return 'success'
  return 'warning' // every intermediate state = in progress
}

interface StateBadgeProps {
  state: string
  isDeferred?: boolean
}

export function StateBadge({ state, isDeferred }: StateBadgeProps) {
  const label = isDeferred ? `${state.replace(/_/g, ' ')} · deferred` : state.replace(/_/g, ' ')
  return (
    <span data-testid="temporal-state-badge" data-state={state} data-deferred={!!isDeferred}>
      <Badge variant={variantFor(state, isDeferred)}>{label}</Badge>
    </span>
  )
}
