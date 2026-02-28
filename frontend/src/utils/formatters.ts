/**
 * Formatting Utilities
 */

/**
 * Format a date as a relative time string (e.g., "2 hours ago")
 */
export function formatTimeAgo(dateString: string | Date | null | undefined): string {
  if (!dateString) return '\u2014'
  const date = typeof dateString === 'string' ? new Date(dateString) : dateString
  if (isNaN(date.getTime())) return '\u2014'
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSeconds = Math.floor(diffMs / 1000)
  const diffMinutes = Math.floor(diffSeconds / 60)
  const diffHours = Math.floor(diffMinutes / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffSeconds < 60) {
    return 'just now'
  } else if (diffMinutes < 60) {
    return `${diffMinutes}m ago`
  } else if (diffHours < 24) {
    return `${diffHours}h ago`
  } else if (diffDays < 7) {
    return `${diffDays}d ago`
  } else {
    return date.toLocaleDateString()
  }
}

/**
 * Escape HTML special characters to prevent XSS
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

/**
 * Convert aggregator hyphenated slug to canonical slashed format.
 * "facebook-react" → "facebook/react"
 * Only replaces the first hyphen (aggregator convention: owner-repo).
 */
export function hyphenatedToSlashed(slug: string): string {
  const idx = slug.indexOf('-')
  return idx === -1 ? slug : slug.substring(0, idx) + '/' + slug.substring(idx + 1)
}

/**
 * Convert canonical slashed slug to aggregator hyphenated format.
 * "facebook/react" → "facebook-react"
 */
export function slashedToHyphenated(slug: string): string {
  return slug.replace('/', '-')
}
