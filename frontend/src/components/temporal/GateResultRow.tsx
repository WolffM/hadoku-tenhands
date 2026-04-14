/**
 * GateResultRow — one row per gate entry from `gates.jsonl`.
 *
 * Shows gate name, verdict badge, reason, and a timestamp.
 */

import { Badge, type BadgeVariant } from '../common/Badge'
import type { TemporalGateRecord } from '../../api/types'

const VERDICT_VARIANT: Record<string, BadgeVariant> = {
  pass: 'success',
  fail: 'danger',
  defer: 'warning'
}

interface GateResultRowProps {
  record: TemporalGateRecord
}

export function GateResultRow({ record }: GateResultRowProps) {
  const variant = VERDICT_VARIANT[record.verdict] || 'secondary'
  return (
    <div
      className="temporal-gate-row"
      data-testid="temporal-gate-row"
      data-gate={record.gate}
      data-verdict={record.verdict}
    >
      <span className="temporal-gate-row__name">{record.gate}</span>
      <Badge variant={variant}>{record.verdict}</Badge>
      {record.reason && <span className="temporal-gate-row__reason">{record.reason}</span>}
      <span className="temporal-gate-row__ts">{record.ts}</span>
    </div>
  )
}
