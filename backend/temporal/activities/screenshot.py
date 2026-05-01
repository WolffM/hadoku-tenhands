"""Test-output → terminal screenshot activity.

When a fix's verification step produces structured test output
(`06-verified/test_output.txt`), this activity:

  1. Renders that output as a terminal-styled PNG via headless
     Chromium (written to `06-verified/after.png`).
  2. Uploads the PNG as a release asset on the fork (under a stable
     `crimson-kitty-assets` release tag — fork releases are invisible
     to the upstream maintainer's PR review surface, so this hosts
     the image without polluting the diff). URL written to
     `06-verified/after_url.txt`.
  3. Returns `{ok, path, url}`.

The render pipeline (`_extract_verification` in `submission.py`)
reads `after_url.txt` and embeds `![Verification](<url>)` at the top
of the Verification section of the upstream PR body. The maintainer
sees the image render inline; nothing about the asset hosting is in
the file diff.

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
- Upload: per-fork release `crimson-kitty-assets`, asset named
  `issue-{N}-after.png`. `gh release upload --clobber` so re-renders
  overwrite cleanly. `browser_download_url` from the asset metadata
  is the public URL we embed.

Why fork release assets instead of the user-content `/upload/policies/
assets` endpoint: that endpoint is cookie-authenticated only — no
token-authenticated equivalent exists. Release assets are the official
stable token-friendly path for hosting binaries on github.com without
committing them to a tracked branch (researched 2026-04-30).
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# Stable release tag on each fork. `gh release upload` to this tag
# adds/overwrites assets without involving any branch's tree.
_ASSETS_RELEASE_TAG = "crimson-kitty-assets"
_ASSETS_RELEASE_TITLE = "Crimson-kitty pipeline assets"
_ASSETS_RELEASE_BODY = (
    "Auto-managed release holding inline-embed assets (test-output "
    "screenshots, etc.) for crimson-kitty pipeline runs on this fork. "
    "Assets are referenced from operator preview PR + upstream PR "
    "bodies via release-asset URLs. Not part of any source branch — "
    "safe to ignore when reviewing fork code."
)


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
    fork_slug: Optional[str] = None,
    issue_number: Optional[int] = None,
    test_output: Optional[str] = None,
    command: Optional[str] = None,
    out_path: str = "06-verified/after.png",
    render_png: Optional[Callable[[str], "asyncio.Future[bytes]"]] = None,
    upload_asset: Optional[Callable[..., dict]] = None,
) -> dict:
    """Render `06-verified/test_output.txt` to a terminal PNG, then upload
    it to the fork's `crimson-kitty-assets` release so a public URL is
    available for embed in the PR body.

    Two-stage failure semantics — render and upload fail independently:
      - Render success + upload failure → `{ok: True, path, url: None,
        upload_error: "..."}`. The PNG is in evidence; `_extract_verification`
        falls back to text-only since there's no URL to embed.
      - Render failure → `{ok: False, reason}`. Upload skipped.

    Seams for tests:
      `render_png(html) -> bytes` — playwright/chromium by default.
      `upload_asset(fork_slug, issue_number, png_bytes, asset_name) ->
        {"ok": bool, "url": str|None, "reason": str|None}` —
        gh-CLI-backed by default.
    """
    if render_png is None:
        render_png = _default_render_png
    if upload_asset is None:
        upload_asset = _default_upload_asset

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

    # Upload to fork release assets so the PNG has a public URL the
    # render pipeline can embed in the upstream PR body. Skip if the
    # caller didn't supply fork_slug/issue_number (tests, dry runs).
    url: Optional[str] = None
    upload_error: Optional[str] = None
    if fork_slug and issue_number is not None:
        asset_name = f"issue-{issue_number}-after.png"
        try:
            up = upload_asset(fork_slug, int(issue_number), png, asset_name)
        except Exception as e:
            logger.warning("screenshot upload raised: %s", e, exc_info=True)
            upload_error = f"{type(e).__name__}: {e}"
        else:
            if isinstance(up, dict) and up.get("ok") and up.get("url"):
                url = up["url"]
                evidence.write_text("06-verified/after_url.txt", url)
            else:
                reason = up.get("reason", "unknown") if isinstance(up, dict) else "non-dict response"
                upload_error = f"upload failed: {reason}"
                logger.warning("screenshot upload failed: %s", upload_error)

    out: dict = {"ok": True, "path": out_path, "bytes": len(png), "url": url}
    if upload_error:
        out["upload_error"] = upload_error
    return out


# ── Release-asset upload helper ───────────────────────────────────────────


def _default_upload_asset(
    fork_slug: str,
    issue_number: int,
    png_bytes: bytes,
    asset_name: str,
) -> dict:
    """Upload `png_bytes` as a release asset on `fork_slug` under the
    `crimson-kitty-assets` release tag. Idempotent: creates the release
    if it doesn't exist, overwrites existing assets with the same name.

    Returns `{ok, url, reason?}`. URL is the asset's
    `browser_download_url` (a `github.com/.../releases/download/...`
    permalink that renders as an image inline when used in markdown
    `![alt](url)`).

    Implementation note: shells out to `gh` CLI rather than using our
    generic `run_gh_command` wrapper because the upload endpoint lives
    on `uploads.github.com` (different host from the regular API), and
    `gh release upload` handles the host switch + content-type +
    multipart encoding for us. Writing the PNG bytes to a temp file is
    necessary because gh's release-upload subcommand wants a file path,
    not stdin.
    """
    import subprocess
    import tempfile

    try:
        from services.github_api import run_gh_command  # type: ignore
    except ImportError:
        return {"ok": False, "reason": "services.github_api not importable"}

    # 1. Ensure the release exists (idempotent — silent if already there).
    check = run_gh_command([
        "api", f"repos/{fork_slug}/releases/tags/{_ASSETS_RELEASE_TAG}",
        "--silent", "-i",
    ])
    if not check.get("success"):
        # Create it. 404 is the expected miss; other failures are real
        # errors we'll propagate via the create call's own success flag.
        create = run_gh_command([
            "release", "create", _ASSETS_RELEASE_TAG,
            "--repo", fork_slug,
            "--title", _ASSETS_RELEASE_TITLE,
            "--notes", _ASSETS_RELEASE_BODY,
        ])
        if not create.get("success"):
            err = (create.get("error") or create.get("output", ""))[:200]
            # Race: another worker created it between our check and create.
            # `gh release create` returns "already exists" — treat as ok.
            if "already exists" not in err.lower():
                return {"ok": False, "reason": f"create release failed: {err}"}

    # 2. Upload the asset. `--clobber` overwrites if `asset_name` is
    #    already present (rerenders for the same issue replace the old
    #    PNG cleanly).
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(png_bytes)
        tmp.flush()
        tmp_path = tmp.name

    try:
        upload = run_gh_command([
            "release", "upload", _ASSETS_RELEASE_TAG,
            f"{tmp_path}#{asset_name}",
            "--repo", fork_slug,
            "--clobber",
        ])
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    if not upload.get("success"):
        err = (upload.get("error") or upload.get("output", ""))[:200]
        return {"ok": False, "reason": f"upload failed: {err}"}

    # 3. Resolve the asset's `browser_download_url`. The upload command
    #    doesn't return JSON metadata; query the release for it.
    view = run_gh_command([
        "api", f"repos/{fork_slug}/releases/tags/{_ASSETS_RELEASE_TAG}",
        "--jq", f'.assets[] | select(.name == "{asset_name}") | .browser_download_url',
    ])
    if not view.get("success"):
        return {"ok": False, "reason": "could not resolve asset url"}
    url = (view.get("output") or "").strip()
    if not url:
        return {"ok": False, "reason": "asset url empty"}

    return {"ok": True, "url": url}
