/**
 * ProgressLog Component
 *
 * Displays a log of actions and their results.
 */

import { usePipelineStore } from '../../store'
import { formatTimeAgo } from '../../utils'

export function ProgressLog() {
  const logs = usePipelineStore(state => state.logs)
  const clearLogs = usePipelineStore(state => state.clearLogs)

  if (logs.length === 0) {
    return null
  }

  return (
    <div className="progress-log">
      <div className="progress-log-header">
        <span className="progress-log-title">Activity Log</span>
        <button className="progress-log-clear" onClick={clearLogs} title="Clear log">
          Clear
        </button>
      </div>
      <div className="progress-log-content">
        {logs.map(entry => (
          <div key={entry.id} className={`progress-log-entry log-${entry.type}`}>
            <span className="log-time">{formatTimeAgo(entry.timestamp)}</span>
            <span className="log-message">{entry.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
