"""
OSSRunnerSetupMixin — self-hosted Actions runner registration.

Handles registering and starting per-repo self-hosted GitHub Actions runners.
Extracted from oss_fork.py for clarity.
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger("pipeline")

# Suppress console windows on Windows when spawning subprocesses
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    from .github_api import run_gh_command
except ImportError:
    from github_api import run_gh_command


class OSSRunnerSetupMixin:
    """Self-hosted Actions runner registration helpers."""

    def _ensure_self_hosted_runner(self, my_user, repo):
        """Register a self-hosted runner for this repo if one isn't already online.

        Uses the GitHub API to get a registration token, then configures and
        starts a runner in a background process. Runners are stored in
        ~/actions-runners/{repo}/.
        """

        # Check if a runner is already registered and online
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/actions/runners",
            "--jq", ".runners[] | select(.status==\"online\") | .name"
        ])
        if result["success"] and result["output"].strip():
            logger.debug("Runner already online for %s/%s: %s",
                         my_user, repo, result["output"].strip().split("\n")[0])
            return

        # Get a registration token
        token_result = run_gh_command([
            "api", "-X", "POST",
            f"repos/{my_user}/{repo}/actions/runners/registration-token",
            "--jq", ".token"
        ])
        if not token_result["success"]:
            logger.warning("Failed to get runner registration token for %s/%s", my_user, repo)
            return

        token = token_result["output"].strip()
        runner_dir = os.path.expanduser(f"~/actions-runners/{repo}")
        runner_bin = os.path.join(runner_dir, "run.sh")

        # If runner directory doesn't exist, set it up
        if not os.path.exists(runner_bin):
            # Find the runner template (first existing runner install to copy from)
            template_dir = None
            runners_base = os.path.expanduser("~/actions-runners")
            os.makedirs(runners_base, exist_ok=True)

            # Look for an existing runner install to symlink/copy from
            home = os.path.expanduser("~")
            for candidate in ["actions-runner", "actions-runner-fastify"]:
                candidate_path = os.path.join(home, candidate)
                if os.path.exists(os.path.join(candidate_path, "run.sh")):
                    template_dir = candidate_path
                    break

            # Also check in the runners directory itself
            if not template_dir:
                for entry in os.listdir(runners_base) if os.path.exists(runners_base) else []:
                    candidate_path = os.path.join(runners_base, entry)
                    if os.path.exists(os.path.join(candidate_path, "run.sh")):
                        template_dir = candidate_path
                        break

            if not template_dir:
                logger.warning(
                    "No runner template found. Please install a GitHub Actions runner at "
                    "~/actions-runners/template/ first. See: "
                    "https://github.com/actions/runner/releases"
                )
                return

            # Copy the runner (can't symlink — each needs its own config)
            logger.info("Setting up runner for %s/%s from %s", my_user, repo, template_dir)
            _flags = _SUBPROCESS_FLAGS
            try:
                subprocess.run(
                    ["cp", "-r", template_dir, runner_dir],
                    capture_output=True, timeout=30, creationflags=_flags
                )
                # Clean old config if copied from another repo's runner
                for stale in [".runner", ".runner_migrated", ".credentials",
                              ".credentials_rsaparams", ".env"]:
                    stale_path = os.path.join(runner_dir, stale)
                    if os.path.exists(stale_path):
                        os.remove(stale_path)
            except Exception as e:
                logger.warning("Failed to copy runner template: %s", e)
                return

        # Configure the runner
        logger.info("Configuring runner for %s/%s", my_user, repo)
        _flags = _SUBPROCESS_FLAGS
        try:
            config_proc = subprocess.run(
                [os.path.join(runner_dir, "config.sh"),
                 "--url", f"https://github.com/{my_user}/{repo}",
                 "--token", token,
                 "--name", f"vd-{repo}",
                 "--labels", "self-hosted,Linux,X64",
                 "--unattended", "--replace"],
                capture_output=True, text=True, timeout=30,
                cwd=runner_dir, creationflags=_flags
            )
            if config_proc.returncode != 0:
                logger.warning("Runner config failed for %s/%s: %s",
                               my_user, repo, config_proc.stderr[:200])
                return
        except Exception as e:
            logger.warning("Runner config error for %s/%s: %s", my_user, repo, e)
            return

        # Start the runner in the background
        logger.info("Starting runner for %s/%s", my_user, repo)
        try:
            subprocess.Popen(
                [os.path.join(runner_dir, "run.sh")],
                stdout=open(os.path.join(runner_dir, "runner.log"), "w"),
                stderr=subprocess.STDOUT,
                cwd=runner_dir,
                start_new_session=True,
            )
            logger.info("Runner started for %s/%s (pid in background)", my_user, repo)
        except Exception as e:
            logger.warning("Failed to start runner for %s/%s: %s", my_user, repo, e)
