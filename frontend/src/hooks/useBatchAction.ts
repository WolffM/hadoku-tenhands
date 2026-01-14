/**
 * useBatchAction - Shared hook for batch operations with real-time UI updates
 *
 * Used across Stage 2, 3, and 4 for consistent handling of:
 * - Processing state
 * - Selection management
 * - Logging
 * - Item removal after success
 */

import { useState, useCallback } from 'react'
import { usePipelineStore } from '../store'

export interface BatchActionResult {
  id: string
  success: boolean
  message?: string
  error?: string
}

export interface UseBatchActionOptions<T> {
  /** Function to process a single item, returns success/error */
  processItem: (item: T) => Promise<{ success: boolean; error?: string }>
  /** Function to get a unique ID for an item */
  getItemId: (item: T) => string
  /** Function to get display name for logging */
  getItemName: (item: T) => string
  /** Called after successful processing of an item */
  onItemSuccess?: (item: T) => void
  /** Action name for logging (e.g., "triggered", "assigned", "merged") */
  actionVerb: string
}

export function useBatchAction<T>(options: UseBatchActionOptions<T>) {
  const { processItem, getItemId, getItemName, onItemSuccess, actionVerb } = options

  const addLog = usePipelineStore(state => state.addLog)
  const [processing, setProcessing] = useState(false)
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())

  const toggleItem = useCallback(
    (item: T) => {
      const id = getItemId(item)
      setSelectedItems(prev => {
        const next = new Set(prev)
        if (next.has(id)) {
          next.delete(id)
        } else {
          next.add(id)
        }
        return next
      })
    },
    [getItemId]
  )

  const selectAll = useCallback(
    (items: T[]) => {
      setSelectedItems(new Set(items.map(getItemId)))
    },
    [getItemId]
  )

  const selectNone = useCallback(() => {
    setSelectedItems(new Set())
  }, [])

  const isSelected = useCallback(
    (item: T) => {
      return selectedItems.has(getItemId(item))
    },
    [selectedItems, getItemId]
  )

  const processSelected = useCallback(
    async (items: T[]) => {
      const selectedList = items.filter(item => selectedItems.has(getItemId(item)))
      if (selectedList.length === 0) return

      setProcessing(true)
      addLog(`Processing ${selectedList.length} items...`, 'info')

      let successCount = 0

      for (const item of selectedList) {
        const itemName = getItemName(item)
        const itemId = getItemId(item)

        try {
          const result = await processItem(item)
          if (result.success) {
            successCount++
            addLog(`${actionVerb} ${itemName}`, 'success')
            // Remove from selection
            setSelectedItems(prev => {
              const next = new Set(prev)
              next.delete(itemId)
              return next
            })
            // Call success callback (e.g., to remove from store)
            onItemSuccess?.(item)
          } else {
            addLog(`Failed on ${itemName}: ${result.error}`, 'error')
          }
        } catch (err) {
          const errorMsg = err instanceof Error ? err.message : 'Unknown error'
          addLog(`Failed on ${itemName}: ${errorMsg}`, 'error')
        }
      }

      addLog(
        `Done! ${successCount}/${selectedList.length} ${actionVerb}`,
        successCount > 0 ? 'success' : 'error'
      )
      setProcessing(false)
    },
    [selectedItems, getItemId, getItemName, processItem, onItemSuccess, actionVerb, addLog]
  )

  const processSingle = useCallback(
    async (item: T) => {
      const itemName = getItemName(item)
      const itemId = getItemId(item)

      addLog(`Processing ${itemName}...`, 'info')

      try {
        const result = await processItem(item)
        if (result.success) {
          addLog(`${actionVerb} ${itemName}`, 'success')
          // Remove from selection if selected
          setSelectedItems(prev => {
            const next = new Set(prev)
            next.delete(itemId)
            return next
          })
          // Call success callback
          onItemSuccess?.(item)
          return true
        } else {
          addLog(`Failed on ${itemName}: ${result.error}`, 'error')
          return false
        }
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Unknown error'
        addLog(`Failed on ${itemName}: ${errorMsg}`, 'error')
        return false
      }
    },
    [getItemId, getItemName, processItem, onItemSuccess, actionVerb, addLog]
  )

  return {
    processing,
    selectedItems,
    selectedCount: selectedItems.size,
    toggleItem,
    selectAll,
    selectNone,
    isSelected,
    processSelected,
    processSingle,
    setSelectedItems
  }
}
