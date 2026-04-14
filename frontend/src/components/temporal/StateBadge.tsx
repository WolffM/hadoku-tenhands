/**
 * StateBadge — color-coded badge for a crimson-kitty issue state.
 *
 * The state taxonomy lives in docs/crimson-kitty/state-machine.md. We map
 * each state to one of the common Badge variants:
 *
 *   success  → terminal success (`merged`)
 *   danger   → terminal failure (`aborted`, `closed_by_upstream`)
 *   warning  → awaiting operator input (`awaiting_human_review`)
 *   primary  → active progress states (candidate → submitted)
 */

import { Badge, type BadgeVariant } from '../common/Badge'

const STATE_VARIANT: Record<string, BadgeVariant> = {
  merged: 'success',
  aborted: 'danger',
  closed_by_upstream: 'danger',
  awaiting_human_review: 'warning',
  submittable: 'info',
  submitted: 'info'
}

function variantFor(state: string): BadgeVariant {
  return STATE_VARIANT[state] || 'primary'
}

interface StateBadgeProps {
  state: string
}

export function StateBadge({ state }: StateBadgeProps) {
  return (
    <span data-testid="temporal-state-badge" data-state={state}>
      <Badge variant={variantFor(state)}>{state.replace(/_/g, ' ')}</Badge>
    </span>
  )
}
