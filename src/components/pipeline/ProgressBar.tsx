/**
 * ProgressBar Component
 *
 * Visual representation of pipeline stage progression.
 */

interface ProgressBarProps {
  current: number
  total: number
  showLabels?: boolean
}

export function ProgressBar({ current, total, showLabels = false }: ProgressBarProps) {
  const percentage = Math.round((current / total) * 100)

  return (
    <div className="progress-bar-container">
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{ width: `${percentage}%` }} />
        {/* Stage markers */}
        {Array.from({ length: total }).map((_, i) => {
          const position = ((i + 1) / total) * 100
          const isCompleted = i + 1 <= current
          const isCurrent = i + 1 === current
          return (
            <div
              key={i}
              className={`progress-marker ${isCompleted ? 'marker-completed' : ''} ${isCurrent ? 'marker-current' : ''}`}
              style={{ left: `${position}%` }}
            />
          )
        })}
      </div>
      {showLabels && (
        <div className="progress-labels">
          <span className="progress-label-current">
            Stage {current} of {total}
          </span>
          <span className="progress-label-percent">{percentage}%</span>
        </div>
      )}
    </div>
  )
}
