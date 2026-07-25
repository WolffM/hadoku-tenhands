"""`ClaudeCodeAgent` — headless `claude -p` inside a pipeline-owned checkout.

The agent is **untrusted** (crimson-kitty principle 4, and it applies harder
here since nobody reviews the diff). Everything below is about bounding what
an untrusted process can reach, because the gates only inspect the *diff* —
by the time they run, the process has already done whatever it was going to.

Three containments, cheapest first:

1. **A checkout it owns.** `checkout.py` puts it in `~/.taskauto/repos/...`,
   never a human's working copy, so a bad `rm -rf` costs a re-clone.
2. **A scrubbed environment.** This is the one that matters most on the
   current host. The tenhands process holds the vault bootstrap key, the
   board key, GitHub tokens and SSO material in its env; a subprocess
   inherits all of it by default. We pass an explicit allow-list instead, so
   the agent gets its own model credential and nothing else. It cannot read
   this repo's secrets even though its parent can.
3. **A wall-clock budget.** An agent that hangs must not hold a claim
   forever.

What this does *not* contain is filesystem access outside the checkout, or
the network. Those need a container or a separate host — see
docs/hadoku-task-automation/README.md §4.3, still open.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

CLAUDE_BIN = os.environ.get("TASKAUTO_CLAUDE_BIN", "claude")
DEFAULT_MODEL = os.environ.get("TASKAUTO_AGENT_MODEL", "sonnet")
DEFAULT_TIMEOUT_S = int(os.environ.get("TASKAUTO_AGENT_TIMEOUT", "1800"))

#: Environment the agent is allowed to see. Everything else is dropped.
#: CLAUDE_CODE_OAUTH_TOKEN is its own credential; the rest is what a process
#: needs to run at all. Notably absent: HADOKU_TASK_KEY, the vault key,
#: TENHANDS_*, GH_TOKEN, GITHUB_TOKEN, SAML_ORG_TOKEN.
ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


class AgentError(RuntimeError):
    """The agent could not be run, or produced nothing usable."""


@dataclass
class AgentRun:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@dataclass
class AgentOutcome:
    """What one agent invocation produced."""

    changed_files: list[str] = field(default_factory=list)
    diff: str = ""
    log: str = ""
    timed_out: bool = False

    @property
    def made_changes(self) -> bool:
        return bool(self.changed_files)


def scrubbed_env(extra: Optional[dict] = None) -> dict:
    """The environment an agent subprocess gets.

    Allow-list, not deny-list, deliberately. A deny-list silently leaks every
    credential someone adds later; an allow-list fails closed, and the failure
    (agent can't reach something) is visible and cheap to fix.
    """
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    if extra:
        env.update(extra)
    return env


def _default_run(args: Sequence[str], cwd: Path, timeout: int,
                 env: dict, stdin_text: Optional[str] = None) -> AgentRun:
    try:
        p = subprocess.run(list(args), cwd=str(cwd), env=env,
                           input=stdin_text, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, check=False)
        return AgentRun(p.returncode == 0, p.stdout, p.stderr)
    except subprocess.TimeoutExpired as e:
        return AgentRun(False, (e.stdout or b"").decode("utf-8", "replace")
                        if isinstance(e.stdout, bytes) else (e.stdout or ""),
                        "timed out", timed_out=True)
    except FileNotFoundError as e:
        raise AgentError(f"{CLAUDE_BIN} not found on PATH") from e


@dataclass
class ClaudeCodeAgent:
    """Runs one prompt to completion in a checkout, then reports the diff."""

    model: str = DEFAULT_MODEL
    timeout_s: int = DEFAULT_TIMEOUT_S
    run: Callable[..., AgentRun] = _default_run
    git: Optional[Callable[..., object]] = None

    def _git(self, args: Sequence[str], cwd: Path) -> tuple[bool, str]:
        if self.git is not None:
            res = self.git(["git", "-C", str(cwd), *args])
            return bool(getattr(res, "ok", False)), getattr(res, "out", "")
        p = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, check=False)
        return p.returncode == 0, p.stdout

    def work(self, checkout: Path, prompt: str) -> AgentOutcome:
        """Run the agent, then read the working tree to see what it did.

        We look at git rather than trusting the agent's account of itself.
        crimson-kitty learned this the expensive way: an agent that reports a
        fix without one is the single most common failure, and the only
        defence that works is measuring the tree instead of reading the
        summary.
        """
        args = [
            CLAUDE_BIN, "-p",
            "--model", self.model,
            # Non-interactive: there is no human to approve a tool call. The
            # containment for this is the scrubbed env and the owned
            # checkout above, plus every gate that inspects the diff after.
            "--dangerously-skip-permissions",
        ]
        res = self.run(args, checkout, self.timeout_s, scrubbed_env(),
                       stdin_text=prompt)

        ok, status = self._git(["status", "--porcelain"], checkout)
        changed = []
        if ok:
            for line in status.splitlines():
                line = line.rstrip()
                if len(line) > 3:
                    changed.append(line[3:].strip().strip('"'))

        _, diff = self._git(["diff", "--"], checkout)
        log = ((res.stdout or "") + ("\n" + res.stderr if res.stderr else ""))

        if res.timed_out:
            logger.warning("agent timed out after %ss with %d file(s) changed",
                           self.timeout_s, len(changed))

        return AgentOutcome(changed_files=sorted(changed), diff=diff,
                            log=log[-20000:], timed_out=res.timed_out)
