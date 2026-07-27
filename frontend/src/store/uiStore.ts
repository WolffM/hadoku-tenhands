/**
 * UI Store Slice
 *
 * activeView, expandedRows, selectedItems, logs, addLog.
 */

// ============ Types (re-exported for consumers) ============

export type ViewType =
  | 'select'
  | 'list'
  | 'review'
  | 'health'
  | 'oss'
  | 'retro'
  | 'temporal'
  | 'taskauto'

export interface LogEntry {
  id: string
  timestamp: Date
  message: string
  type: 'info' | 'success' | 'error' | 'warning'
}

export interface UISliceState {
  activeView: ViewType
  expandedRows: Set<string>
  selectedItems: Set<string>
  logs: LogEntry[]

  setActiveView: (view: ViewType) => void
  toggleRowExpanded: (id: string) => void
  toggleItemSelected: (id: string) => void
  selectAll: () => void
  selectNone: () => void
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

export function createUISlice<S extends UISliceState & { pipelineItems: { id: string }[] }>(
  set: (fn: (state: S) => Partial<S>) => void,
  _get: () => S
): UISliceState {
  return {
    activeView: 'select',
    expandedRows: new Set(),
    selectedItems: new Set(),
    logs: [],

    setActiveView: (view: ViewType) => set(_s => ({ activeView: view }) as Partial<S>),

    toggleRowExpanded: (id: string) => {
      set(s => {
        const newExpanded = new Set(s.expandedRows)
        if (newExpanded.has(id)) {
          newExpanded.delete(id)
        } else {
          newExpanded.add(id)
        }
        return { expandedRows: newExpanded } as Partial<S>
      })
    },

    toggleItemSelected: (id: string) => {
      set(s => {
        const newSelected = new Set(s.selectedItems)
        if (newSelected.has(id)) {
          newSelected.delete(id)
        } else {
          newSelected.add(id)
        }
        return { selectedItems: newSelected } as Partial<S>
      })
    },

    selectAll: () => {
      set(
        s =>
          ({
            selectedItems: new Set(s.pipelineItems.map(item => item.id))
          }) as Partial<S>
      )
    },

    selectNone: () => {
      set(_s => ({ selectedItems: new Set() }) as Partial<S>)
    },

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
