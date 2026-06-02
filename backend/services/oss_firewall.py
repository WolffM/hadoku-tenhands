"""
OSSFirewallMixin — Copilot coding agent firewall management.

Handles disabling the Copilot firewall via REST API or patchright browser
automation as a fallback. The _PATCHRIGHT_LOCK semaphore limits concurrent
Chromium launches to prevent WSL OOM crashes.

Extracted from oss_fork.py for clarity.
"""

import logging
import os
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

_SUBPROCESS_FLAGS = 0

# Global semaphore: patchright launches a headless Chromium (~300MB each).
# Multiple concurrent dispatches can crash WSL via OOM. Limit to 1 at a time.
_PATCHRIGHT_LOCK = threading.Semaphore(1)

try:
    from .github_api import run_gh_command
except ImportError:
    from github_api import run_gh_command


class OSSFirewallMixin:
    """Copilot coding agent firewall disable helpers."""

    def _disable_copilot_firewall(self, my_user, repo):
        """Disable the Copilot coding agent firewall asynchronously.

        Spawns a daemon thread so the dispatch request thread is not blocked.
        The firewall only needs to be disabled before Copilot starts working
        (minutes later), so there's no reason to wait inline.
        """
        t = threading.Thread(
            target=self._run_firewall_disable,
            args=(my_user, repo),
            daemon=True,
            name=f"patchright-{my_user}-{repo}",
        )
        t.start()
        logger.info("Firewall disable launched in background for %s/%s", my_user, repo)

    def _run_firewall_disable(self, my_user, repo):
        """Blocking implementation for firewall disable — runs in a background thread.

        Tries the REST API first. Falls back to patchright browser automation.
        The _PATCHRIGHT_LOCK semaphore limits concurrent Chromium instances to 1.
        """

        # Try API first (best-effort — endpoint may not exist yet)
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/copilot/coding_agent/settings",
            "-X", "PATCH",
            "-f", "firewall_enabled=false"
        ])
        if result["success"]:
            logger.info("Disabled Copilot firewall via API on %s/%s", my_user, repo)
            return

        # REST API failed — fall back to patchright browser automation
        logger.debug("Copilot firewall API call failed for %s/%s: %s — trying patchright", my_user, repo, result.get("error"))
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scripts", "disable-copilot-firewall.py"
        )
        if not os.path.exists(script_path):
            logger.warning(
                "Cannot disable Copilot firewall on %s/%s — no API and script not found at %s. "
                "Disable manually at: https://github.com/%s/%s/settings/copilot/coding_agent",
                my_user, repo, script_path, my_user, repo
            )
            return

        logger.info("Disabling Copilot firewall via patchright on %s/%s", my_user, repo)
        _flags = _SUBPROCESS_FLAGS
        # acquire(timeout=300): wait up to 5 min for another patchright to finish
        if not _PATCHRIGHT_LOCK.acquire(timeout=300):
            logger.warning(
                "Patchright semaphore timeout for %s/%s — skipping firewall disable",
                my_user, repo
            )
            return
        try:
            proc = subprocess.run(
                [sys.executable, script_path, f"{my_user}/{repo}"],
                capture_output=True, text=True, timeout=60,
                creationflags=_flags,
            )
            if proc.returncode == 0:
                logger.info("Copilot firewall disabled on %s/%s via patchright", my_user, repo)
            else:
                logger.warning(
                    "Patchright firewall disable failed on %s/%s: %s",
                    my_user, repo, proc.stderr[:200]
                )
        except subprocess.TimeoutExpired:
            logger.warning("Patchright firewall disable timed out on %s/%s", my_user, repo)
        except Exception as e:
            logger.warning("Patchright firewall disable error on %s/%s: %s", my_user, repo, e)
        finally:
            _PATCHRIGHT_LOCK.release()
