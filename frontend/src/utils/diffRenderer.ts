/**
 * Diff Renderer Utility
 *
 * Converts git diff output to HTML for display.
 */

import { escapeHtml } from './formatters'

export interface DiffFile {
  filename: string
  additions: number
  deletions: number
  lines: DiffLine[]
}

export interface DiffLine {
  type: 'addition' | 'deletion' | 'context' | 'header' | 'hunk'
  content: string
  oldLineNumber?: number
  newLineNumber?: number
}

/**
 * Parse a git diff string into structured data
 */
export function parseDiff(diffText: string): DiffFile[] {
  const files: DiffFile[] = []
  const lines = diffText.split('\n')

  let currentFile: DiffFile | null = null
  let oldLineNum = 0
  let newLineNum = 0

  for (const line of lines) {
    // New file header
    if (line.startsWith('diff --git')) {
      if (currentFile) {
        files.push(currentFile)
      }
      // Extract filename from diff --git a/path b/path
      const regex = /diff --git a\/(.*) b\/(.*)/
      const match = regex.exec(line)
      const filename = match ? match[2] : 'unknown'
      currentFile = {
        filename,
        additions: 0,
        deletions: 0,
        lines: []
      }
      currentFile.lines.push({ type: 'header', content: line })
      continue
    }

    if (!currentFile) continue

    // File metadata headers
    if (
      line.startsWith('index ') ||
      line.startsWith('---') ||
      line.startsWith('+++') ||
      line.startsWith('new file') ||
      line.startsWith('deleted file') ||
      line.startsWith('rename from') ||
      line.startsWith('rename to')
    ) {
      currentFile.lines.push({ type: 'header', content: line })
      continue
    }

    // Hunk header (@@ -start,count +start,count @@)
    if (line.startsWith('@@')) {
      const hunkRegex = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/
      const match = hunkRegex.exec(line)
      if (match) {
        oldLineNum = parseInt(match[1], 10)
        newLineNum = parseInt(match[2], 10)
      }
      currentFile.lines.push({ type: 'hunk', content: line })
      continue
    }

    // Addition
    if (line.startsWith('+')) {
      currentFile.additions++
      currentFile.lines.push({
        type: 'addition',
        content: line.substring(1),
        newLineNumber: newLineNum++
      })
      continue
    }

    // Deletion
    if (line.startsWith('-')) {
      currentFile.deletions++
      currentFile.lines.push({
        type: 'deletion',
        content: line.substring(1),
        oldLineNumber: oldLineNum++
      })
      continue
    }

    // Context line
    if (line.startsWith(' ') || line === '') {
      currentFile.lines.push({
        type: 'context',
        content: line.substring(1) || '',
        oldLineNumber: oldLineNum++,
        newLineNumber: newLineNum++
      })
    }
  }

  if (currentFile) {
    files.push(currentFile)
  }

  return files
}

/**
 * Render a diff to HTML string
 */
export function renderDiffToHtml(diffText: string): string {
  const files = parseDiff(diffText)

  if (files.length === 0) {
    return '<div class="diff-empty">No changes</div>'
  }

  let html = ''

  for (const file of files) {
    html += `<div class="diff-file">`
    html += `<div class="diff-file-header">`
    html += `<span class="diff-filename">${escapeHtml(file.filename)}</span>`
    html += `<span class="diff-stats">`
    html += `<span class="diff-additions">+${file.additions}</span>`
    html += `<span class="diff-deletions">-${file.deletions}</span>`
    html += `</span>`
    html += `</div>`
    html += `<div class="diff-content">`
    html += `<table class="diff-table">`

    for (const line of file.lines) {
      if (line.type === 'header') {
        html += `<tr class="diff-line diff-line-header">`
        html += `<td class="diff-line-num"></td>`
        html += `<td class="diff-line-num"></td>`
        html += `<td class="diff-line-content">${escapeHtml(line.content)}</td>`
        html += `</tr>`
      } else if (line.type === 'hunk') {
        html += `<tr class="diff-line diff-line-hunk">`
        html += `<td class="diff-line-num" colspan="2"></td>`
        html += `<td class="diff-line-content">${escapeHtml(line.content)}</td>`
        html += `</tr>`
      } else {
        const lineClass = `diff-line diff-line-${line.type}`
        const oldNum = line.oldLineNumber ?? ''
        const newNum = line.newLineNumber ?? ''
        const prefix = line.type === 'addition' ? '+' : line.type === 'deletion' ? '-' : ' '

        html += `<tr class="${lineClass}">`
        html += `<td class="diff-line-num diff-line-num-old">${oldNum}</td>`
        html += `<td class="diff-line-num diff-line-num-new">${newNum}</td>`
        html += `<td class="diff-line-content"><span class="diff-prefix">${prefix}</span>${escapeHtml(line.content)}</td>`
        html += `</tr>`
      }
    }

    html += `</table>`
    html += `</div>`
    html += `</div>`
  }

  return html
}

/**
 * Get summary stats from diff
 */
export function getDiffStats(diffText: string): {
  files: number
  additions: number
  deletions: number
} {
  const files = parseDiff(diffText)
  return {
    files: files.length,
    additions: files.reduce((sum, f) => sum + f.additions, 0),
    deletions: files.reduce((sum, f) => sum + f.deletions, 0)
  }
}
