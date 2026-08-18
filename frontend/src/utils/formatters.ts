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
 * Format a duration in seconds as "1h 04m", "11m 32s" or "42s".
 *
 * Rounded, never precise: these are agent wall-clock numbers a human reads to
 * answer "was that quick or slow", and a millisecond tail only makes that
 * harder to skim.
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !isFinite(seconds) || seconds < 0) return '—'
  const total = Math.round(seconds)
  if (total < 60) return `${total}s`
  const mins = Math.floor(total / 60)
  if (mins < 60) return `${mins}m ${String(total % 60).padStart(2, '0')}s`
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`
}

/**
 * Format a timestamp as "Jul 27, 21:16" in the reader's locale and zone.
 *
 * Relative time is the right default almost everywhere in this app, and the
 * wrong one on a timeline: three events on the same day all read "2d ago",
 * which erases the ordering the timeline exists to show.
 */
export function formatTimestamp(dateString: string | null | undefined): string {
  if (!dateString) return '—'
  const date = new Date(dateString)
  if (isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

/**
 * Escape HTML special characters to prevent XSS.
 *
 * Deliberately a string substitution rather than the `div.textContent →
 * div.innerHTML` trick this used to be. Two reasons, in order:
 *
 *  1. That trick needs a live DOM, which made every module that touched it —
 *     `diffRenderer` included — impossible to test outside a browser. This is
 *     pure string work and has no business requiring one.
 *  2. It allocates a DOM element per call, and `diffRenderer` calls it once
 *     per line of a diff.
 *
 * The quote entities are the one deliberate difference from the old output:
 * the serializer left `"` and `'` alone because it only ever produced element
 * content, where they are harmless. Escaping them costs nothing there (the
 * browser renders `&quot;` as `"`) and makes the result safe to interpolate
 * into an attribute, which the old one silently was not.
 */
const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, char => HTML_ESCAPES[char])
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
