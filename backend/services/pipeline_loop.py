"""
Background pipeline advancement loop.

Periodically checks all assignments and advances each one through
the Stage 4 pipeline (4a → 4b → 4c → 4d → retrospective).

Started automatically on app boot. Disable with PIPELINE_LOOP_ENABLED=false.
"""

import logging
import os
import threading
import time

logger = logging.getLogger("pipeline.loop")

DEFAULT_POLL_INTERVAL = int(os.environ.get("PIPELINE_POLL_INTERVAL", "90"))
MIN_ADVANCE_INTERVAL = int(os.environ.get("PIPELINE_MIN_ADVANCE_INTERVAL", "60"))


class PipelineLoop:
    """Background daemon thread that advances all active assignments."""

    def __init__(self, app, poll_interval=None, min_advance_interval=None):
        self.app = app
        self.poll_interval = poll_interval or DEFAULT_POLL_INTERVAL
        self.min_advance_interval = min_advance_interval or MIN_ADVANCE_INTERVAL
        self._thread = None
        self._stop_event = threading.Event()
        self._last_advance = {}  # (repo, fork_issue_number) -> monotonic timestamp

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("Pipeline loop already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="pipeline-loop"
        )
        self._thread.start()
        logger.info(
            "Pipeline loop started (poll=%ds, min_advance=%ds)",
            self.poll_interval, self.min_advance_interval,
        )

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Pipeline loop stopped")

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        # Let Flask finish startup before first tick
        self._stop_event.wait(10)

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("Pipeline loop tick failed")
            self._stop_event.wait(self.poll_interval)

    def _tick(self):
        with self.app.app_context():
            from .github_api import get_authenticated_user, set_saml_token_override, is_saml_org
            from . import OSSService
            from .pipeline_orchestrator import PipelineOrchestrator
            from .pipeline_logger import log_event

            my_user = get_authenticated_user()
            if my_user == "unknown":
                logger.warning("Pipeline loop: cannot authenticate, skipping tick")
                return

            svc = OSSService()
            assignments = svc.get_assigned_issues()

            terminal_states = {"retrospective_complete"}
            active = [
                a for a in assignments
                if a.get("stage4_status", "swe_agent_working") not in terminal_states
            ]

            if not active:
                return

            logger.info("Pipeline loop: %d active assignment(s)", len(active))

            orchestrator = PipelineOrchestrator(oss_service=svc)
            now = time.monotonic()

            for assignment in active:
                key = (assignment.get("repo"), assignment.get("fork_issue_number"))
                last = self._last_advance.get(key, 0)

                if now - last < self.min_advance_interval:
                    continue

                status_before = assignment.get("stage4_status", "swe_agent_working")
                origin_slug = assignment.get("origin_slug", "")
                issue_number = assignment.get("issue_number")

                # Activate SAML token for forks of SAML-protected orgs.
                # The fork (WolffM/repo) inherits SAML enforcement from
                # the upstream org, so all gh commands need the SAML token.
                origin_owner = origin_slug.split("/")[0] if "/" in origin_slug else ""
                if is_saml_org(origin_owner):
                    set_saml_token_override(origin_owner.lower())

                try:
                    result = orchestrator.advance(assignment, {"my_user": my_user})
                    self._last_advance[key] = time.monotonic()

                    status_after = result.get("status", status_before)
                    advanced = result.get("advanced", False)

                    if advanced:
                        logger.info(
                            "Pipeline loop: advanced %s #%s: %s → %s",
                            origin_slug, issue_number, status_before, status_after,
                        )
                        log_event(
                            "stage4", "auto-advance", origin_slug, issue_number,
                            status="ok",
                            detail=f"{status_before} → {status_after}",
                        )
                    else:
                        logger.debug(
                            "Pipeline loop: %s #%s still at %s",
                            origin_slug, issue_number, status_after,
                        )

                except Exception:
                    logger.exception(
                        "Pipeline loop: error advancing %s #%s", origin_slug, issue_number,
                    )
                finally:
                    set_saml_token_override(None)

            # Clean stale throttle entries
            active_keys = {
                (a.get("repo"), a.get("fork_issue_number")) for a in active
            }
            for k in list(self._last_advance):
                if k not in active_keys:
                    del self._last_advance[k]


_loop_instance = None


def start_pipeline_loop(app):
    """Start the background pipeline loop. Call once from app.py."""
    global _loop_instance

    enabled = os.environ.get("PIPELINE_LOOP_ENABLED", "true").lower()
    if enabled not in ("true", "1", "yes"):
        logger.info("Pipeline loop disabled (PIPELINE_LOOP_ENABLED=%s)", enabled)
        return

    _loop_instance = PipelineLoop(app)
    _loop_instance.start()


def stop_pipeline_loop():
    """Stop the background pipeline loop."""
    global _loop_instance
    if _loop_instance:
        _loop_instance.stop()
        _loop_instance = None


def get_loop_status():
    """Return current loop status for the status endpoint."""
    if not _loop_instance:
        return {"running": False, "enabled": False}
    return {
        "running": _loop_instance.running,
        "enabled": True,
        "poll_interval": _loop_instance.poll_interval,
        "min_advance_interval": _loop_instance.min_advance_interval,
    }
