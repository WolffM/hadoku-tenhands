"""Tests for the test-output → terminal screenshot activity.

Most tests use a stub renderer so they don't need a chromium binary.
One end-to-end test launches real chromium and is skipped cleanly if
the browser isn't installed (CI without `playwright install chromium`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temporal.evidence.store import EvidenceStore


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


def _stub_renderer(captured: list[str]):
    """Build a renderer that captures the HTML it was given and returns
    canned PNG bytes. Useful for asserting on HTML composition without
    actually launching chromium."""

    async def _render(html: str) -> bytes:
        captured.append(html)
        # Minimal valid 1×1 PNG (89 bytes). Enough to exercise the
        # write-bytes path; tests that need real pixels run separately.
        return bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452"
            "0000000100000001080600000001f15c"
            "4d0000000d49444154789c63000000000"
            "0000005000168f74e8c0000000049454e44ae426082"
        )

    return _render


def _stub_uploader(captured_uploads: list[dict], *, ok: bool = True, url: str = "https://github.com/WolffM/demo/releases/download/crimson-kitty-assets/issue-42-after.png", reason: str | None = None):
    """Build an upload stub that captures its inputs and returns a
    canned response. Useful for asserting on what gets uploaded
    without making real GitHub API calls."""

    def _upload(fork_slug: str, issue_number: int, png_bytes: bytes, asset_name: str) -> dict:
        captured_uploads.append({
            "fork_slug": fork_slug,
            "issue_number": issue_number,
            "png_bytes_len": len(png_bytes),
            "asset_name": asset_name,
        })
        if ok:
            return {"ok": True, "url": url}
        return {"ok": False, "reason": reason or "stub failure"}

    return _upload


@pytest.mark.asyncio
async def test_render_writes_png_when_test_output_present(ev):
    """Happy path: test_output.txt exists → activity composes HTML +
    delegates to renderer + writes PNG to 06-verified/after.png."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text(
        "06-verified/test_output.txt",
        "ok      github.com/gofiber/fiber/v3/middleware/logger    0.034s\n"
        "PASS",
    )

    captured: list[str] = []
    uploads: list[dict] = []
    result = await render_test_output_screenshot(
        ev,
        fork_slug="WolffM/demo",
        issue_number=42,
        command="go test ./middleware/logger/...",
        render_png=_stub_renderer(captured),
        upload_asset=_stub_uploader(uploads),
    )

    assert result["ok"] is True
    assert result["path"] == "06-verified/after.png"
    assert result["bytes"] > 0
    assert ev.exists("06-verified/after.png")
    # The HTML the renderer received should contain the command and output
    assert len(captured) == 1
    html = captured[0]
    assert "go test ./middleware/logger/..." in html
    assert "github.com/gofiber/fiber/v3/middleware/logger" in html
    # PASS keyword should be highlighted via the ok span class
    assert '<span class="ok">PASS</span>' in html
    # Three traffic-light dots should be in the chrome
    assert 'class="dot r"' in html
    assert 'class="dot y"' in html
    assert 'class="dot g"' in html


@pytest.mark.asyncio
async def test_render_returns_failure_when_output_missing(ev):
    """No test_output.txt on disk → activity returns ok=False without
    crashing the workflow. This is the fallback path: the workflow
    drops back to text-only verification via _extract_verification."""
    from temporal.activities.screenshot import render_test_output_screenshot

    captured: list[str] = []
    result = await render_test_output_screenshot(
        ev, render_png=_stub_renderer(captured),
    )

    assert result["ok"] is False
    assert "no test_output.txt" in result["reason"]
    assert not ev.exists("06-verified/after.png")
    assert len(captured) == 0  # renderer never invoked


@pytest.mark.asyncio
async def test_render_returns_failure_when_output_empty(ev):
    """Whitespace-only test_output is treated the same as missing — no
    PNG is produced. Pointless to render an empty terminal."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text("06-verified/test_output.txt", "   \n  \t\n")

    captured: list[str] = []
    result = await render_test_output_screenshot(
        ev, render_png=_stub_renderer(captured),
    )

    assert result["ok"] is False
    assert "empty" in result["reason"]
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_render_strips_ansi_codes(ev):
    """ANSI color codes from go test, pytest, etc. are stripped before
    the HTML is built — they'd render as raw `[31m` garbage otherwise."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text(
        "06-verified/test_output.txt",
        "\x1b[32mPASS\x1b[0m: TestFoo\n\x1b[31mFAIL\x1b[0m: TestBar\n",
    )

    captured: list[str] = []
    await render_test_output_screenshot(
        ev, render_png=_stub_renderer(captured),
    )

    html = captured[0]
    # Raw ANSI escape sequences should be gone
    assert "\x1b[" not in html
    assert "[32m" not in html
    assert "[31m" not in html
    # But the highlight spans for PASS/FAIL should be there
    assert '<span class="ok">PASS</span>' in html
    assert '<span class="fail">FAIL</span>' in html


@pytest.mark.asyncio
async def test_render_highlights_pass_fail_keywords(ev):
    """Pass/fail visual signal is the whole point of the screenshot.
    Verify both spans appear when both keywords are in the output."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text(
        "06-verified/test_output.txt",
        "=== RUN   TestA\n"
        "--- PASS: TestA (0.01s)\n"
        "=== RUN   TestB\n"
        "--- FAIL: TestB (0.02s)\n"
        "    foo_test.go:12: expected 1, got 2\n"
        "FAIL\n"
        "FAIL    example.com/foo    0.040s\n",
    )

    captured: list[str] = []
    await render_test_output_screenshot(
        ev, render_png=_stub_renderer(captured),
    )

    html = captured[0]
    # At least one ok span (the --- PASS: line)
    assert html.count('class="ok"') >= 1
    # At least one fail span
    assert html.count('class="fail"') >= 1


@pytest.mark.asyncio
async def test_render_escapes_html_in_test_output(ev):
    """Test output containing HTML-special chars (<, >, &) must be
    escaped, otherwise we'd render real DOM and e.g. inject scripts.
    Defense-in-depth — even though test output isn't user-controlled
    by external actors, this is upstream-visible content."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text(
        "06-verified/test_output.txt",
        'expected: <Element id="x">; got: <script>alert(1)</script>\n'
        "PASS\n",
    )

    captured: list[str] = []
    await render_test_output_screenshot(
        ev, render_png=_stub_renderer(captured),
    )

    html = captured[0]
    # The literal <script> tag from test output must NOT be in the page;
    # it must be escaped to &lt;script&gt;
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # Same for the <Element ...> snippet
    assert "&lt;Element" in html


@pytest.mark.asyncio
async def test_render_passes_through_explicit_test_output_arg(ev):
    """Tests can pass `test_output=` directly to bypass the disk read,
    useful for assertions where seeding a file is overhead."""
    from temporal.activities.screenshot import render_test_output_screenshot

    captured: list[str] = []
    result = await render_test_output_screenshot(
        ev,
        test_output="all good\nPASS",
        command="custom-runner",
        render_png=_stub_renderer(captured),
    )

    assert result["ok"] is True
    assert "all good" in captured[0]
    assert "custom-runner" in captured[0]


@pytest.mark.asyncio
async def test_render_handles_renderer_exception(ev):
    """Renderer raising → activity returns ok=False with the error
    message. Workflow should NOT crash on a screenshot failure — text
    fallback is acceptable."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text("06-verified/test_output.txt", "PASS")

    async def boom(html: str) -> bytes:
        raise RuntimeError("chromium missing")

    result = await render_test_output_screenshot(
        ev, render_png=boom,
    )

    assert result["ok"] is False
    assert "chromium missing" in result["reason"]
    assert not ev.exists("06-verified/after.png")


# ── Upload path tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_uploads_asset_and_writes_url_when_fork_slug_provided(ev):
    """When fork_slug + issue_number are passed, the activity uploads
    the PNG to the fork's release assets and writes the resulting
    public URL to 06-verified/after_url.txt for the body renderer."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text("06-verified/test_output.txt", "PASS\nok 0.04s")

    captured_renders: list[str] = []
    captured_uploads: list[dict] = []
    result = await render_test_output_screenshot(
        ev,
        fork_slug="WolffM/demo",
        issue_number=42,
        command="go test ./...",
        render_png=_stub_renderer(captured_renders),
        upload_asset=_stub_uploader(
            captured_uploads,
            url="https://github.com/WolffM/demo/releases/download/crimson-kitty-assets/issue-42-after.png",
        ),
    )

    assert result["ok"] is True
    assert result["url"] == (
        "https://github.com/WolffM/demo/releases/download/"
        "crimson-kitty-assets/issue-42-after.png"
    )
    # URL persists to evidence so _extract_verification can read it
    assert ev.exists("06-verified/after_url.txt")
    assert ev.read_text("06-verified/after_url.txt").strip() == result["url"]
    # Upload received the right metadata
    assert len(captured_uploads) == 1
    upload = captured_uploads[0]
    assert upload["fork_slug"] == "WolffM/demo"
    assert upload["issue_number"] == 42
    assert upload["asset_name"] == "issue-42-after.png"
    assert upload["png_bytes_len"] > 0


@pytest.mark.asyncio
async def test_render_skips_upload_when_fork_slug_missing(ev):
    """Without fork_slug+issue_number, no upload happens. The PNG
    still lands in evidence; the workflow can use it locally for
    inspection but no URL is embedded in the upstream PR body."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text("06-verified/test_output.txt", "PASS\nok")

    captured_uploads: list[dict] = []
    result = await render_test_output_screenshot(
        ev,
        render_png=_stub_renderer([]),
        upload_asset=_stub_uploader(captured_uploads),
    )

    assert result["ok"] is True
    assert result["url"] is None
    assert not ev.exists("06-verified/after_url.txt")
    assert len(captured_uploads) == 0


@pytest.mark.asyncio
async def test_render_treats_upload_failure_as_non_fatal(ev):
    """Upload failure ≠ render failure. The PNG was produced; the
    workflow can still ship the fix, just without the inline image
    embed. result["ok"] stays True; url is None; upload_error
    documents the failure for retro/debugging."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text("06-verified/test_output.txt", "PASS")

    result = await render_test_output_screenshot(
        ev,
        fork_slug="WolffM/demo",
        issue_number=42,
        render_png=_stub_renderer([]),
        upload_asset=_stub_uploader([], ok=False, reason="rate limited"),
    )

    assert result["ok"] is True
    assert result["url"] is None
    assert "rate limited" in result["upload_error"]
    assert ev.exists("06-verified/after.png")
    assert not ev.exists("06-verified/after_url.txt")


@pytest.mark.asyncio
async def test_render_treats_upload_exception_as_non_fatal(ev):
    """Same shape as the failure-with-reason case, but for raised
    exceptions (network errors, missing gh binary, etc.). Still
    non-fatal."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text("06-verified/test_output.txt", "PASS")

    def boom_uploader(fork_slug, issue_number, png_bytes, asset_name):
        raise RuntimeError("no network")

    result = await render_test_output_screenshot(
        ev,
        fork_slug="WolffM/demo",
        issue_number=42,
        render_png=_stub_renderer([]),
        upload_asset=boom_uploader,
    )

    assert result["ok"] is True
    assert result["url"] is None
    assert "no network" in result["upload_error"]


# ── End-to-end test with real chromium ────────────────────────────────────


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as p:
            path = p.chromium.executable_path
            return bool(path) and Path(path).exists()
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _chromium_available(),
    reason="chromium binary not installed; run `playwright install chromium`",
)
async def test_render_end_to_end_produces_real_png(ev):
    """Real-renderer smoke test: launch chromium, render a tiny HTML,
    get back a valid PNG. Skipped in CI without `playwright install`."""
    from temporal.activities.screenshot import render_test_output_screenshot

    ev.write_text(
        "06-verified/test_output.txt",
        "PASS  TestExample (0.01s)\nok  github.com/example/foo  0.034s",
    )

    result = await render_test_output_screenshot(
        ev, command="go test ./...",
    )

    assert result["ok"] is True
    assert result["bytes"] > 1000  # real PNG, not the 89-byte stub

    # Verify the on-disk file is a valid PNG (magic bytes 89 50 4E 47)
    png_path = Path(ev.path("06-verified/after.png"))
    head = png_path.read_bytes()[:8]
    assert head == b"\x89PNG\r\n\x1a\n", f"not a PNG: {head.hex()}"


# ── renderer resilience ───────────────────────────────────────────────────
#
# `Page.captureScreenshot` fails transiently when the renderer is starved.
# The pm2 host routinely has dozens of Chromium processes competing, and a
# raised exception here means the run produces no evidence at all, so the
# retry is worth a test rather than a comment.


class _FakePlaywright:
    """Minimal async_playwright() stand-in. Fails `fail_times` launches."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.launches = 0
        self.launch_args = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def chromium(self):
        return self

    async def launch(self, headless=True, args=None):
        self.launches += 1
        self.launch_args.append(list(args or []))
        if self.launches <= self.fail_times:
            raise RuntimeError("Protocol error (Page.captureScreenshot): "
                               "Unable to capture screenshot")
        return _FakeBrowser()


class _FakeBrowser:
    async def new_page(self, viewport=None):
        return _FakePage()

    async def close(self):
        return None


class _FakePage:
    async def set_content(self, html, wait_until=None):
        return None

    async def screenshot(self, type=None, full_page=None):
        return b"\x89PNG\r\n\x1a\n" + b"x" * 200


def _install_fake(monkeypatch, fake):
    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_a_starved_renderer_is_retried_not_surfaced(monkeypatch):
    from temporal.activities import screenshot

    fake = _install_fake(monkeypatch, _FakePlaywright(fail_times=1))
    png = await screenshot._default_render_png("<html></html>")

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert fake.launches == 2, "the first failure should have been retried"


@pytest.mark.asyncio
async def test_a_persistently_failing_renderer_still_raises(monkeypatch):
    # Retrying forever would hide a real breakage behind a slow green.
    from temporal.activities import screenshot

    fake = _install_fake(monkeypatch, _FakePlaywright(fail_times=99))
    with pytest.raises(RuntimeError, match="Unable to capture screenshot"):
        await screenshot._default_render_png("<html></html>")

    assert fake.launches == screenshot._RENDER_ATTEMPTS


@pytest.mark.asyncio
async def test_chromium_is_launched_with_the_hardening_flags(monkeypatch):
    from temporal.activities import screenshot

    fake = _install_fake(monkeypatch, _FakePlaywright(fail_times=0))
    await screenshot._default_render_png("<html></html>")

    assert "--disable-dev-shm-usage" in fake.launch_args[0]
