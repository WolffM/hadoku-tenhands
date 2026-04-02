import { useState, useCallback } from 'react'
import { usePipelineStore } from '../store'

type MsgResult = Record<string, unknown>

interface UseAsyncActionOptions {
  /** Message logged before the action starts. Can be a function of the call key. */
  startMsg: string | ((key: string) => string)
  /** Message logged on success. Receives the result and the call key. */
  successMsg: string | ((result: MsgResult, key: string) => string)
  /** Message logged on failure. result.error is appended when available. */
  failMsg: string
  /** Called after a successful action (e.g., to reload data). */
  onSuccess?: (result: MsgResult) => void | Promise<void>
}

/**
 * Hook for single-item async actions with loading state, log messages, and
 * optional success callback.
 *
 * Returns [loadingKey, run] where:
 * - loadingKey is the key passed to run() while the action is in flight, null otherwise
 * - run(key, fn) executes fn, manages loading state, and logs results
 *
 * For multi-item batch flows use useBatchAction instead.
 */
export function useAsyncAction(
  opts: UseAsyncActionOptions
): [
  string | null,
  (key: string, fn: () => Promise<{ success: boolean; error?: string }>) => Promise<void>
] {
  const [loading, setLoading] = useState<string | null>(null)
  const addLog = usePipelineStore(state => state.addLog)

  const run = useCallback(
    async (key: string, fn: () => Promise<{ success: boolean; error?: string }>) => {
      setLoading(key)
      const start = typeof opts.startMsg === 'function' ? opts.startMsg(key) : opts.startMsg
      if (start) addLog(start, 'info')
      try {
        const result = await fn()
        if (result.success) {
          const r = result as MsgResult
          const msg =
            typeof opts.successMsg === 'function' ? opts.successMsg(r, key) : opts.successMsg
          if (msg) addLog(msg, 'success')
          await opts.onSuccess?.(r)
        } else {
          addLog(result.error ? `${opts.failMsg}: ${result.error}` : opts.failMsg, 'error')
        }
      } catch (err) {
        const msg = err instanceof Error ? `: ${err.message}` : ''
        addLog(`${opts.failMsg}${msg}`, 'error')
      } finally {
        setLoading(null)
      }
    },
    [opts.startMsg, opts.successMsg, opts.failMsg, opts.onSuccess, addLog]
  )

  return [loading, run]
}
