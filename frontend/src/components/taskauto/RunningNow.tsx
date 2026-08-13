/**
 * RunningNow — the tasks an agent currently holds a claim on.
 *
 * This is the only part of the page that answers "is the pipeline alive right
 * now", so it stays at the top and renders even when empty: an explicit "no
 * agent is working" is information, whereas a hidden section reads as a
 * broken page.
 */

import { Badge, EmptyState, SectionHeader } from '../common'
import type { TaskAutoStatus } from '../../api/types'

interface RunningNowProps {
  running: TaskAutoStatus['running']
}

export function RunningNow({ running }: RunningNowProps) {
  return (
    <section className="taskauto-section" data-testid="taskauto-running">
      <SectionHeader icon="⚙️" title="Running now" count={running.length} />
      {running.length === 0 ? (
        <EmptyState
          icon="💤"
          title="No agent is working"
          description="Agents pick up work on a schedule — a quiet moment here is normal."
        />
      ) : (
        <ul className="taskauto-list">
          {running.map(t => (
            <li key={t.id} className="taskauto-list__item">
              <span className="taskauto-pulse" aria-hidden="true" />
              <Badge variant="info">{t.lane}</Badge>
              <span className="taskauto-list__title">{t.title}</span>
              <span className="taskauto-list__meta">{t.repo}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
