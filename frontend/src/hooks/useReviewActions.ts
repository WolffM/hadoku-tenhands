/**
 * useReviewActions - Shared hook for PR approve/merge operations
 *
 * Extracts the common approve/merge try-catch-log pattern used across
 * Stage4Review, StageDetails, and ReviewCarousel.
 */

import { useState, useCallback } from 'react'
import { approvePR, mergePR } from '../api/endpoints'
import { getErrorMessage } from '../utils'

interface UseReviewActionsOptions {
  owner: string | null
  addLog: (msg: string, type: 'info' | 'success' | 'error') => void
  onAfterApprove?: (repo: string, prNumber: number) => void | Promise<void>
  onAfterMerge?: (repo: string, prNumber: number) => void | Promise<void>
}

export function useReviewActions({
  owner,
  addLog,
  onAfterApprove,
  onAfterMerge
}: UseReviewActionsOptions) {
  const [actionLoading, setActionLoading] = useState(false)

  const approve = useCallback(
    async (repo: string, prNumber: number) => {
      if (!owner) return
      setActionLoading(true)
      addLog(`Approving ${repo}#${prNumber}...`, 'info')

      try {
        const result = await approvePR(owner, repo, prNumber)
        if (result.success) {
          addLog(`Approved ${repo}#${prNumber}`, 'success')
          await onAfterApprove?.(repo, prNumber)
        } else {
          addLog(`Failed: ${result.error}`, 'error')
        }
      } catch (err) {
        addLog(`Error: ${getErrorMessage(err)}`, 'error')
      } finally {
        setActionLoading(false)
      }
    },
    [owner, addLog, onAfterApprove]
  )

  const merge = useCallback(
    async (repo: string, prNumber: number) => {
      if (!owner) return
      setActionLoading(true)
      addLog(`Merging ${repo}#${prNumber}...`, 'info')

      try {
        const result = await mergePR(owner, repo, prNumber)
        if (result.success) {
          addLog(`Merged ${repo}#${prNumber}`, 'success')
          await onAfterMerge?.(repo, prNumber)
        } else {
          addLog(`Failed: ${result.error}`, 'error')
        }
      } catch (err) {
        addLog(`Error: ${getErrorMessage(err)}`, 'error')
      } finally {
        setActionLoading(false)
      }
    },
    [owner, addLog, onAfterMerge]
  )

  return { actionLoading, approve, merge }
}
