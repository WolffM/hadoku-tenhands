"""
Disable the Copilot coding agent firewall on a GitHub repository.

Uses patchright (Playwright fork) to automate the UI toggle since
GitHub provides no API for this setting. Required for self-hosted
runners to work with the Copilot coding agent.

Usage:
    python scripts/disable-copilot-firewall.py login          # one-time GitHub login
    python scripts/disable-copilot-firewall.py owner/repo     # disable firewall
    python scripts/disable-copilot-firewall.py owner/repo1 owner/repo2 ...

First run 'login' to authenticate. Session persists in ~/.config/patchright-gh/.
"""

import sys
import os
import time
import logging

from patchright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("firewall")

BROWSER_DATA_DIR = os.path.expanduser("~/.config/patchright-gh")


def _launch_browser(p, headless=False):
    """Launch a persistent Chromium context."""
    return p.chromium.launch_persistent_context(
        BROWSER_DATA_DIR,
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 800},
    )


def do_login():
    """Interactive login — opens a browser window for the user to authenticate."""
    os.makedirs(BROWSER_DATA_DIR, exist_ok=True)
    log.info("Opening browser for GitHub login...")
    log.info("Please log in, then close the browser window when done.")

    with sync_playwright() as p:
        browser = _launch_browser(p, headless=False)
        page = browser.new_page()
        page.goto("https://github.com/login", wait_until="networkidle", timeout=30000)

        log.info("Waiting for login... (close browser when done)")
        try:
            while True:
                time.sleep(2)
                url = page.url
                if "login" not in url and "session" not in url:
                    log.info("Logged in! Current URL: %s", url)
                    break
        except Exception:
            pass

        time.sleep(2)
        page.close()
        browser.close()

    log.info("Session saved to %s", BROWSER_DATA_DIR)


def _is_logged_in(page):
    """Check if we're logged into GitHub."""
    try:
        body_text = page.inner_text("body", timeout=5000)[:1000]
        return "Sign in to GitHub" not in body_text
    except Exception:
        return False


def disable_firewall(page, owner, repo):
    """Navigate to the Copilot coding agent settings and disable the firewall.

    The settings page is at /{owner}/{repo}/settings/copilot/coding_agent.
    The firewall uses GitHub's Primer ToggleSwitch components:
    - button.prc-ToggleSwitch-SwitchButton with aria-pressed="true"/"false"
    - The first toggle on the page is "Enable firewall"
    - The heading above it has id "sweagentd-firewall-ui-enable-label"
    """
    url = f"https://github.com/{owner}/{repo}/settings/copilot/coding_agent"
    log.info("Navigating to %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)

    if not _is_logged_in(page):
        log.error("Not logged in. Run: python %s login", sys.argv[0])
        return False

    page_text = page.inner_text("body", timeout=5000)
    if "Copilot coding agent" not in page_text:
        log.error("Not on coding agent settings page for %s/%s", owner, repo)
        return False

    # Find the "Enable firewall" toggle
    # Strategy 1: Find the heading and then the toggle button near it
    firewall_heading = page.locator("#sweagentd-firewall-ui-enable-label")
    if firewall_heading.count() == 0:
        firewall_heading = page.locator("text=Enable firewall")
    if firewall_heading.count() == 0:
        log.warning("No 'Enable firewall' heading found on %s/%s", owner, repo)
        return False

    # The toggle is a sibling/nearby button with class prc-ToggleSwitch-SwitchButton
    # Walk up to the containing section and find the toggle
    toggle = None

    # Try: find the toggle in the parent container of the heading
    heading_el = firewall_heading.first
    for depth in range(1, 6):
        ancestor = heading_el.locator(f"xpath=ancestor::*[{depth}]")
        if ancestor.count() == 0:
            continue
        btn = ancestor.first.locator("button.prc-ToggleSwitch-SwitchButton-1CtM6")
        if btn.count() == 0:
            # Try with partial class match
            btn = ancestor.first.locator('button[class*="SwitchButton"]')
        if btn.count() > 0:
            toggle = btn.first
            break

    # Fallback: first toggle button on the page (it's the firewall one)
    if toggle is None:
        all_toggles = page.locator('button[class*="SwitchButton"]').all()
        if all_toggles:
            toggle = all_toggles[0]
            log.info("Using first toggle on page (fallback)")

    if toggle is None:
        log.warning("Could not find firewall toggle button on %s/%s", owner, repo)
        return False

    # Always toggle ON then OFF to force GitHub to register the "off" state.
    # New forks may show firewall as "off" in the UI but GitHub's backend
    # still injects COPILOT_AGENT_FIREWALL_ENABLED=true until the toggle is
    # explicitly clicked at least once.
    aria_pressed = toggle.get_attribute("aria-pressed")
    log.info("Firewall toggle: aria-pressed=%s (firewall %s)",
             aria_pressed, "ON" if aria_pressed == "true" else "OFF")

    if aria_pressed == "false":
        # Toggle ON first so we can toggle it OFF (forces state registration)
        toggle.click()
        time.sleep(1.5)
        log.info("Toggled firewall ON (intermediate step)")

    # Now toggle OFF
    toggle.click()
    time.sleep(1.5)

    new_state = toggle.get_attribute("aria-pressed")
    if new_state == "false":
        log.info("Firewall disabled on %s/%s", owner, repo)
        return True
    else:
        log.warning("Toggle click didn't change state on %s/%s (still %s)",
                   owner, repo, new_state)
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  python {sys.argv[0]} login              # one-time GitHub login")
        print(f"  python {sys.argv[0]} owner/repo         # disable firewall")
        print(f"  python {sys.argv[0]} owner/repo1 owner/repo2 ...")
        sys.exit(1)

    if sys.argv[1] == "login":
        do_login()
        return

    repos = []
    for arg in sys.argv[1:]:
        if "/" not in arg:
            print(f"Invalid repo format: {arg} (expected owner/repo)")
            sys.exit(1)
        owner, repo = arg.split("/", 1)
        repos.append((owner, repo))

    os.makedirs(BROWSER_DATA_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = _launch_browser(p, headless=True)
        page = browser.new_page()

        page.goto("https://github.com", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        if not _is_logged_in(page):
            page.close()
            browser.close()
            log.error("Not logged in. Run: python %s login", sys.argv[0])
            sys.exit(1)

        log.info("GitHub session active")

        results = {}
        for owner, repo in repos:
            try:
                success = disable_firewall(page, owner, repo)
                results[f"{owner}/{repo}"] = success
            except Exception as e:
                log.error("Failed on %s/%s: %s", owner, repo, e)
                results[f"{owner}/{repo}"] = False

        page.close()
        browser.close()

    print("\n=== Results ===")
    for slug, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  {slug}: {status}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
