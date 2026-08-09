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

from . import proc

logger = logging.getLogger(__name__)

CLAUDE_BIN = os.environ.get("TASKAUTO_CLAUDE_BIN", "claude")
DEFAULT_MODEL = os.environ.get("TASKAUTO_AGENT_MODEL", "sonnet")
DEFAULT_TIMEOUT_S = int(os.environ.get("TASKAUTO_AGENT_TIMEOUT", "1800"))

#: Memory ceiling for the agent *and its whole subprocess tree*. Higher than
#: `proc.DEFAULT_MEMORY_MAX` because an agent legitimately runs installs and
#: builds; still far below the ~19 GB one runaway typecheck reached alone.
AGENT_MEMORY_MAX = os.environ.get("TASKAUTO_AGENT_MEMORY_MAX", "12G")

#: Environment the agent is allowed to see. Everything else is dropped.
#: CLAUDE_CODE_OAUTH_TOKEN is its own credential; the rest is what a process
#: needs to run at all. Notably absent: HADOKU_SERVICE_KEY, the vault key,
#: TENHANDS_*, GH_TOKEN, GITHUB_TOKEN, SAML_ORG_TOKEN.
ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


class AgentError(RuntimeError):
    """The agent ran and this task got nothing usable out of it.

    Task-scoped: another task might well succeed. The runner stalls the task
    with the reason and carries on.
    """


class AgentUnavailable(AgentError):
    """The agent could not run AT ALL. Every task will fail identically.

    The distinction is the whole point, and it cost us a task to learn it. On
    2026-08-08 `CLAUDE_CODE_OAUTH_TOKEN` was revoked; `claude -p` exited 1 in
    3.5s having printed `Failed to authenticate. API Error: 401 OAuth access
    token has been revoked.` — **on stdout, with stderr empty**. `ask` checked
    only for a timeout and for empty output, so that sentence became the plan.
    It parsed to an empty document, which `jobs.plan_job` read as "neither a
    plan nor a question" and released to `plan-review` as `no-action-proposed`
    — the branch that means "this looks already done". The run reported
    SUCCESS. A human got a task back saying `_No open questions._` and nothing
    else, with no way to tell that the agent had never run.

    So this is raised, never swallowed, and it is not a stall: stalling asks a
    human to look at a *task* that has nothing wrong with it. It aborts the
    run, which turns the health check red — the honest signal, because the
    pipeline really is down until someone replaces the credential.
    """


@dataclass
class AgentRun:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    #: Carried through from `proc.Ran` rather than folded into `stderr` text,
    #: because callers have to tell a *pathological task* (this one blew the
    #: memory ceiling) from a *broken pipeline* (nothing can run) — and those
    #: want opposite responses: stall the task, versus fail the whole run.
    out_of_memory: bool = False


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
    """Run the agent inside a cgroup that bounds everything it spawns.

    This was a plain `subprocess.run(timeout=)`, and that is what let the
    2026-07-29 outage happen. The agent is not one process, it is a *tree*, and
    the interesting members are grandchildren it spawns from its own Bash tool
    — a typecheck, a test run, a build. `subprocess.run`'s timeout kills only
    the direct child, so three runaway typechecks survived both the timeout and
    the runner's exit, were reparented to init, and grew to ~46 GB combined.
    `proc.py` has the full anatomy.

    Containment #3 in the module docstring above ("a wall-clock budget") was
    the one that turned out to be a promise this function could not keep. It
    can now.

    The memory ceiling covers the whole tree rather than the agent alone, which
    is what makes it useful: when a pathological child blows past it, the
    kernel OOM-kills the biggest member of the cgroup — that child, not
    `claude` — so the agent survives, sees its tool call fail, and carries on.
    """
    try:
        res = proc.run(list(args), cwd=cwd, timeout=timeout, env=env,
                       stdin_text=stdin_text,
                       memory_max=AGENT_MEMORY_MAX, label="agent")
    except FileNotFoundError as e:
        raise AgentUnavailable(f"{CLAUDE_BIN} not found on PATH") from e

    if res.out_of_memory:
        # Neither a timeout nor an ordinary failure, and worth saying which:
        # a timeout wants a longer budget, this wants somebody to look at what
        # the agent ran.
        logger.error("the agent's process tree exceeded %s and was killed",
                     AGENT_MEMORY_MAX)
        return AgentRun(False, res.out,
                        (res.err or "") + f"\nkilled: the agent's process tree "
                        f"exceeded {AGENT_MEMORY_MAX}",
                        out_of_memory=True)
    return AgentRun(res.ok, res.out, res.err, timed_out=res.timed_out)


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

    def ask(self, checkout: Path, prompt: str, *,
            timeout_s: Optional[int] = None) -> str:
        """Run a read-only analysis pass and return what it said.

        Planning reads a repo and writes a document; it has no business
        editing files. Splitting this from `work` keeps the file-changing
        capability out of the planning path entirely, rather than granting
        it and hoping the prompt is obeyed.
        """
        args = [CLAUDE_BIN, "-p", "--model", self.model,
                "--allowed-tools", "Read,Grep,Glob,Bash(git log:*),Bash(git show:*)"]
        res = self.run(args, checkout, timeout_s or self.timeout_s,
                       scrubbed_env(), stdin_text=prompt)
        if res.timed_out:
            raise AgentError(f"planning timed out after {timeout_s or self.timeout_s}s")
        out = (res.stdout or "").strip()
        # Exit status FIRST, and before the emptiness check, because the
        # failure we actually hit was neither a timeout nor silence: a dead
        # credential exits non-zero and writes a one-line error to *stdout*.
        # Guarding only on `not out` reads that line as the agent's answer.
        #
        # This pass is read-only — Read/Grep/Glob and two git subcommands — so
        # no prompt can make the CLI exit non-zero on its own. A failure here
        # is the CLI failing, which is every task's problem, not this one's.
        if not res.ok:
            detail = (res.stderr or "").strip() or out or "no output"
            raise AgentUnavailable(
                f"{CLAUDE_BIN} exited non-zero and produced no plan: "
                f"{detail[:300]}")
        if not out:
            raise AgentError(
                f"planning produced no output: {(res.stderr or '')[:300]}")
        return out

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

        # Failed, changed nothing, and neither ran out of time nor out of
        # memory: it never got going. Measuring the tree cannot tell that
        # apart from "read the plan and decided against it", and the caller
        # reads an empty tree as the latter — `implement:no-changes` stalls
        # the task and asks a human to explain themselves about a task that
        # is fine. Same laundering `ask` used to do, one lane along.
        #
        # A timeout or an OOM kill IS this task's problem, and one changed
        # file means it got far enough to have an opinion; both fall through
        # to the tree measurement, which stays the arbiter of what happened.
        if not res.ok and not changed and not res.timed_out \
                and not res.out_of_memory:
            detail = ((res.stderr or "").strip()
                      or (res.stdout or "").strip() or "no output")
            raise AgentUnavailable(
                f"{CLAUDE_BIN} exited non-zero having changed nothing: "
                f"{detail[:300]}")

        return AgentOutcome(changed_files=sorted(changed), diff=diff,
                            log=log[-20000:], timed_out=res.timed_out)
