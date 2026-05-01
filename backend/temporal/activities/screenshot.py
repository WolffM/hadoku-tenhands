"""Test-output → terminal screenshot activity.

When a fix's verification step produces structured test output
(`06-verified/test_output.txt`), this activity renders that output as
a terminal-styled PNG (`06-verified/after.png`). The render pipeline
embeds the PNG inline in the upstream PR's Verification section, so
the maintainer sees visual proof of the fix passing tests instead of
a templated "Reviewers can run the test suite" prose paragraph.

Design (locked 2026-04-30):
- Renderer: headless Chromium via `playwright`. Browser binary lives
  at `~/.cache/ms-playwright/`. If unavailable, the activity returns
  `{ok: False}` and the workflow falls back to text-only verification
  (the existing `_extract_verification` path).
- Template: dark background (Catppuccin Mocha base #1e1e2e), three
  traffic-light dots + command-line title bar, monospace body. ANSI
  escape codes are stripped server-side; PASS/FAIL keywords are
  highlighted via simple regex-driven CSS spans (green / red).
- Sizing: 1280×720 viewport. Tall outputs scroll inside the terminal
  body — we only screenshot the visible viewport so the resulting PNG
  doesn't grow unbounded with test count.
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── ANSI escape stripping ─────────────────────────────────────────────────
#
# Test runners (go test, pytest, cargo test, jest) emit ANSI color codes
# in their output. We strip them before rendering — the HTML template
# doesn't interpret raw `\x1b[31m...\x1b[0m`, and embedding a JS lib
# (ansi_up) just to interpret colors adds a dependency and bytes for
# little benefit. Heuristic coloring (next section) recovers the
# pass/fail signal without per-byte ANSI awareness.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


# ── Pass/fail heuristic coloring ──────────────────────────────────────────
#
# Common test-runner output patterns. We wrap matched substrings with
# `<span class="ok">` / `<span class="fail">` so the CSS in the template
# colors them. Order matters — patterns are checked in sequence, first
# match wins, so list more specific ones first.
_PASS_PATTERNS = [
    re.compile(r"\b(PASS|PASSED|ok|OK)\b"),
    re.compile(r"^---?\s+PASS:.*$", re.MULTILINE),  # go test
    re.compile(r"^✓.*$", re.MULTILINE),               # jest, mocha
]
_FAIL_PATTERNS = [
    re.compile(r"\b(FAIL|FAILED|ERROR|FAILURE)\b"),
    re.compile(r"^---?\s+FAIL:.*$", re.MULTILINE),
    re.compile(r"^✗.*$", re.MULTILINE),
    re.compile(r"^Traceback.*$", re.MULTILINE),       # python
]


def _highlight(text: str) -> str:
    """Wrap pass/fail substrings in CSS class spans. Operates on raw
    text BEFORE HTML-escaping; the escape happens after this — so we
    insert literal `<span>` tags here that survive escaping by being
    re-stitched.

    Approach: scan text linearly, build (kind, span) tuples, then
    HTML-escape each span and re-emit with the surrounding `<span
    class=...>`. Avoids the regex-replace-into-escaped-text headache.
    """
    # Linear scan: collect (start, end, kind) hits, sorted, non-overlapping
    hits: list[tuple[int, int, str]] = []
    for pat in _PASS_PATTERNS:
        for m in pat.finditer(text):
            hits.append((m.start(), m.end(), "ok"))
    for pat in _FAIL_PATTERNS:
        for m in pat.finditer(text):
            hits.append((m.start(), m.end(), "fail"))
    # Resolve overlaps: sort by start, drop any hit that starts before
    # the previous hit's end (keep first-found, since order is
    # significant — pass list comes first so passes dominate).
    hits.sort(key=lambda h: (h[0], -h[1]))
    keep: list[tuple[int, int, str]] = []
    last_end = -1
    for h in hits:
        if h[0] >= last_end:
            keep.append(h)
            last_end = h[1]

    # Reconstruct with HTML-escape + span wrapping
    out: list[str] = []
    cursor = 0
    for start, end, kind in keep:
        if cursor < start:
            out.append(_html.escape(text[cursor:start]))
        out.append(f'<span class="{kind}">{_html.escape(text[start:end])}</span>')
        cursor = end
    out.append(_html.escape(text[cursor:]))
    return "".join(out)


# ── HTML template ─────────────────────────────────────────────────────────
#
# Three-dot title bar mimicking macOS Terminal / iTerm2 chrome, then a
# `<pre>` body for the test output. The title is the test command (if
# we know it) or "verification". Width clamped to 1200px so long lines
# wrap inside the terminal box rather than blowing past the viewport.
_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    html, body { margin: 0; padding: 0; background: #11111b; height: 100vh;
                  font-family: 'Cascadia Code', 'Menlo', 'Consolas', monospace; }
    .terminal {
      width: 1200px; margin: 24px auto; border-radius: 10px; overflow: hidden;
      background: #1e1e2e; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      border: 1px solid #313244;
    }
    .titlebar {
      display: flex; align-items: center; padding: 10px 14px;
      background: #181825; border-bottom: 1px solid #313244;
    }
    .dots { display: flex; gap: 8px; }
    .dot { width: 12px; height: 12px; border-radius: 50%; }
    .dot.r { background: #f38ba8; }
    .dot.y { background: #f9e2af; }
    .dot.g { background: #a6e3a1; }
    .title { flex: 1; text-align: center; color: #cdd6f4; font-size: 13px; }
    .body {
      padding: 16px 18px; color: #cdd6f4; font-size: 13px; line-height: 1.5;
      white-space: pre-wrap; word-break: break-word;
    }
    .ok   { color: #a6e3a1; font-weight: 600; }
    .fail { color: #f38ba8; font-weight: 600; }
  </style>
</head>
<body>
  <div class="terminal">
    <div class="titlebar">
      <div class="dots"><div class="dot r"></div><div class="dot y"></div><div class="dot g"></div></div>
      <div class="title">__TITLE__</div>
    </div>
    <pre class="body">__BODY__</pre>
  </div>
</body>
</html>
"""


def _build_html(test_output: str, command: Optional[str]) -> str:
    cleaned = _strip_ansi(test_output or "")
    body_html = _highlight(cleaned)
    title = _html.escape(command or "verification")
    return (
        _HTML_TEMPLATE
        .replace("__TITLE__", title)
        .replace("__BODY__", body_html)
    )


# ── Renderer ──────────────────────────────────────────────────────────────


async def _default_render_png(html: str) -> bytes:
    """Default renderer using headless Chromium via Playwright.

    Loads `html` into a blank page, sets a 1280×720 viewport, screenshots
    the full visible area to PNG bytes. Tall outputs that overflow the
    viewport get clipped — that's intentional, the resulting PNG should
    fit in a PR body without being a 5MB scroll-saver.
    """
    from playwright.async_api import async_playwright  # type: ignore

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.set_content(html, wait_until="networkidle")
            png = await page.screenshot(type="png", full_page=False)
            return png
        finally:
            await browser.close()


async def render_test_output_screenshot(
    evidence,
    *,
    test_output: Optional[str] = None,
    command: Optional[str] = None,
    out_path: str = "06-verified/after.png",
    render_png: Optional[Callable[[str], "asyncio.Future[bytes]"]] = None,
) -> dict:
    """Render `06-verified/test_output.txt` (or the explicit `test_output`
    arg, for tests) into a terminal-styled PNG at `out_path`.

    Returns:
      `{"ok": True, "path": "<rel>", "bytes": <int>}` on success.
      `{"ok": False, "reason": "<why>"}` if the input is missing or the
      render itself fails. Failures are non-fatal — the workflow proceeds
      with text-only verification via `_extract_verification`.

    Seam for tests: `render_png` is the callable that turns HTML into
    PNG bytes. Default is the playwright/chromium implementation; tests
    pass a stub that returns canned bytes so we can assert on the path
    and HTML composition without needing a browser binary.
    """
    if render_png is None:
        render_png = _default_render_png

    if test_output is None:
        if not evidence.exists("06-verified/test_output.txt"):
            return {"ok": False, "reason": "no test_output.txt"}
        test_output = evidence.read_text("06-verified/test_output.txt")

    if not test_output or not test_output.strip():
        return {"ok": False, "reason": "test_output empty"}

    html = _build_html(test_output, command)
    try:
        png = await render_png(html)
    except Exception as e:
        logger.warning("screenshot render failed: %s", e, exc_info=True)
        return {"ok": False, "reason": f"render failed: {e}"}

    if not png:
        return {"ok": False, "reason": "render produced empty bytes"}

    evidence.write_bytes(out_path, png)
    return {"ok": True, "path": out_path, "bytes": len(png)}
