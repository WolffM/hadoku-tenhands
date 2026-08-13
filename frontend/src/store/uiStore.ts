/**
 * UI Store Slice
 *
 * activeView, logs, addLog.
 */

// ============ Types (re-exported for consumers) ============

export type ViewType =
  'select' | 'list' | 'health' | 'oss' | 'retro' | 'temporal' | 'taskauto'

export interface LogEntry {
  id: string
  timestamp: Date
  message: string
  type: 'info' | 'success' | 'error' | 'warning'
}

export interface UISliceState {
  activeView: ViewType
  logs: LogEntry[]

  setActiveView: (view: ViewType) => void
  addLog: (message: string, type: LogEntry['type']) => void
  clearLogs: () => void
}

// ============ Helper ============

function createLogEntry(message: string, type: LogEntry['type'] = 'info'): LogEntry {
  return {
    id: `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    timestamp: new Date(),
    message,
    type
  }
}

// ============ Slice Creator ============

export function createUISlice<S extends UISliceState>(
  set: (fn: (state: S) => Partial<S>) => void,
  _get: () => S
): UISliceState {
  return {
    activeView: 'select',
    logs: [],

    setActiveView: (view: ViewType) => set(_s => ({ activeView: view }) as Partial<S>),

    addLog: (message: string, type: LogEntry['type'] = 'info') => {
      set(
        s =>
          ({
            logs: [...s.logs, createLogEntry(message, type)]
          }) as Partial<S>
      )
    },

    clearLogs: () => {
      set(_s => ({ logs: [] as LogEntry[] }) as Partial<S>)
    }
  }
}
