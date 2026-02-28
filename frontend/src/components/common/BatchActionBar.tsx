/**
 * BatchActionBar Component
 *
 * Standard Select All / Select None / Process Selected button group.
 * Renders fragments (no wrapper div) — designed as SectionHeader children.
 */

interface BatchActionBarProps {
  onSelectAll: () => void
  onSelectNone: () => void
  onProcess: () => void
  selectedCount: number
  processLabel: string
  processing: boolean
}

export function BatchActionBar({
  onSelectAll,
  onSelectNone,
  onProcess,
  selectedCount,
  processLabel,
  processing,
}: BatchActionBarProps) {
  return (
    <>
      <button className="btn btn--secondary btn--sm" onClick={onSelectAll}>
        Select All
      </button>
      <button className="btn btn--secondary btn--sm" onClick={onSelectNone}>
        Select None
      </button>
      <button
        className="btn btn--primary btn--sm"
        onClick={onProcess}
        disabled={processing || selectedCount === 0}
      >
        {processLabel} ({selectedCount})
      </button>
    </>
  )
}
