import { test, expect } from '@playwright/test'

import { escapeHtml, hyphenatedToSlashed } from '../../src/utils/formatters'

test('escapes the characters that can break out of markup', () => {
  expect(escapeHtml('<script>alert("x" & \'y\')</script>')).toBe(
    '&lt;script&gt;alert(&quot;x&quot; &amp; &#39;y&#39;)&lt;/script&gt;'
  )
})

test('escapes the ampersand once, not twice', () => {
  // The classic double-escape: `&amp;` must not become `&amp;amp;`.
  expect(escapeHtml('a & b')).toBe('a &amp; b')
  expect(escapeHtml('&amp;')).toBe('&amp;amp;')
})

test('leaves text with nothing to escape untouched', () => {
  expect(escapeHtml('')).toBe('')
  expect(escapeHtml('plain ascii, é, and 日本語')).toBe('plain ascii, é, and 日本語')
})

test('splits an aggregator slug on its first hyphen only', () => {
  expect(hyphenatedToSlashed('facebook-react')).toBe('facebook/react')
  expect(hyphenatedToSlashed('WolffM-hadoku-tenhands')).toBe('WolffM/hadoku-tenhands')
})
