"""Spawning a subprocess that cannot outlive us, and cannot eat the host.

This exists because of an outage on 2026-07-29. The agent ran
`timeout 90 npx --yes -p typescript tsc --noEmit -p .` inside a POC checkout.
`npx` resolved `typescript` to *latest* — 7.0.2, whose `tsc` is a
statically-linked Go binary — which then went non-convergent on three.js TSL
types at a steady ~130 MB/s. Three of them accumulated ~46 GB RSS and drove a
61 GB workstation to 3.4 GB available. Each was still at 100% CPU and growing
when it was killed by hand.

Every layer that should have stopped it failed, and each failure is a separate
lesson this module encodes:

1. **`subprocess.run(timeout=)` kills one process, not a process tree.**
   CPython calls `Popen.kill()` on the direct child. Anything that child
   spawned is untouched. `timeout(1)` has the same shape of hole from the
   other direction.
2. **A signal only reaches processes it can address.** The native compiler
   dies on SIGTERM perfectly well — measured — so it did not ignore the
   signal, the signal never arrived. Something between `npx` and the compiler
   left the process group being signalled, so a group-wide kill missed it.
   Which link did that is still unproven, and *this module is written so that
   it does not matter*: the cgroup below kills by **membership**, not by
   signal reachability, and membership is not something a child can opt out
   of.
3. **An orphan is adopted, not reaped.** When the runner exited, its
   grandchildren were reparented to PID 1 and kept running. Nothing in the
   pipeline was left holding a handle on them.
4. **Nothing bounded the memory.** A Go binary has no equivalent of V8's
   `--max-old-space-size`, so it never self-aborts the way a runaway Node
   process eventually does. Swap absorbed 40 GB and turned a job that should
   have died into a machine-wide outage.

So: **one cgroup per invocation, with limits systemd enforces.**

    systemd-run --user --scope
        -p MemoryMax=<cap>      the tree dies instead of the host
        -p MemorySwapMax=0      no 40 GB of swap papering over it
        -p RuntimeMaxSec=<t>    a wall clock PID 1 owns, not us

`RuntimeMaxSec` is the one that closes lesson 3 properly. Every other
mechanism here — our own timeout, the atexit reaper, `PDEATHSIG` — runs in
*this* process, so a `kill -9` of the runner defeats all of them. That ceiling
lives in systemd, so it fires whether or not we are alive to fire it. It is
the only guarantee in this file that survives our own sudden death.

**Why a memory cap does not simply move the failure.** `MemoryMax` on the
scope makes the kernel OOM-kill *within* the cgroup, and it picks the biggest
member — the runaway compiler, not the agent that invoked it. So the agent
survives, sees its tool call fail, and can react. Capping the agent's whole
tree is therefore gentler than it sounds: the pathological job dies and the
work continues.

**Secrets must not reach the command line.** With `--scope`, `systemd-run`
execs the command in its own process, so our `env=` is inherited directly —
verified, along with stdin and exit-code passthrough. That matters for more
than tidiness: the alternative, `--setenv=K=V`, would put
`CLAUDE_CODE_OAUTH_TOKEN` into a command line any local user can read out of
`/proc/*/cmdline`.

**The one wrinkle that costs us an `env -u`.** `systemd-run --user` needs
`XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` to find the user bus, and the
agent's scrubbed environment deliberately contains neither. Handing them
through would work and would also hand an untrusted agent a live D-Bus
handle — enough to talk to `systemd --user` and stop other units. So they are
added to `systemd-run`'s own environment and stripped again from the workload
with `env -u`, which keeps the allow-list in `agent.py` honest. A test asserts
the strip, because the failure mode is silent.

**When systemd is not there.** A headless runner may have no user D-Bus
session. Detection is a probe, not a guess, and the fallback is honest: new
session + process-group kill + `PDEATHSIG`, which handles the ordinary cases
and cannot promise the rest. It logs once, loudly, that the hard ceilings are
unavailable — a silent downgrade to "no limits" is how this outage happened in
the first place.
"""

from __future__ import annotations

import atexit
import errno
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

#: Memory ceiling for one invocation *and everything it spawns*. 8 GiB is
#: comfortably more than a real build needs and far below the ~19 GB a single
#: runaway typecheck reached. Raise it per call rather than globally.
DEFAULT_MEMORY_MAX = os.environ.get("TASKAUTO_MEMORY_MAX", "8G")

#: Set `TASKAUTO_NO_CGROUP=1` to force the fallback path — for testing it, and
#: for hosts where the probe passes but the limits are known-bad.
FORCE_NO_CGROUP = os.environ.get("TASKAUTO_NO_CGROUP", "") == "1"

#: Between SIGTERM and SIGKILL. Long enough for a test runner to flush its
#: output, short enough that a wedged process does not hold the pipeline.
KILL_GRACE_S = 5

#: Slack between our timeout and systemd's. Ours should normally win, because
#: ours produces a diagnosable `Ran(timed_out=True)` and systemd's just
#: removes the processes. `RuntimeMaxSec` is the backstop for when we are gone.
RUNTIME_MAX_SLACK_S = 30

#: What `systemd-run --user` needs in its own environment to reach the user
#: bus, and what the workload must not inherit. See the module docstring.
_BUS_VARS = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")

#: prctl(2). `PR_SET_PDEATHSIG` asks the kernel to signal the child when its
#: parent dies — the only reaping that works when the parent is SIGKILLed and
#: runs no cleanup of its own. It covers the *direct* child only; descendants
#: need the cgroup.
_PR_SET_PDEATHSIG = 1


@dataclass
class Ran:
    """The result of one contained invocation."""

    ok: bool
    out: str = ""
    err: str = ""
    timed_out: bool = False
    #: True when the tree was killed for exceeding its memory ceiling. Worth
    #: distinguishing: a timeout usually means "slow", this means "broken",
    #: and they want different responses from a caller.
    out_of_memory: bool = False
    returncode: Optional[int] = None


# ── live-tree registry ───────────────────────────────────────────────────────
#
# Every tree we start is registered here until it exits, so that an exit path
# which is not the normal one can still take them all down. Keyed by pgid
# because that is what we can signal; the scope unit is what we can kill by
# membership when it exists.

_live: dict[int, str] = {}
_live_lock = threading.Lock()
_handlers_installed = False
_scope_ok: Optional[bool] = None


def _register(pgid: int, unit: str) -> None:
    with _live_lock:
        _live[pgid] = unit


def _forget(pgid: int) -> None:
    with _live_lock:
        _live.pop(pgid, None)


def _kill_scope(unit: str) -> None:
    """Kill every process in `unit`'s cgroup, whatever group they moved to.

    This is the part a child cannot escape. `stop` after `kill` because a scope
    whose processes are gone still lingers as a unit otherwise.
    """
    if not unit:
        return
    for argv in (["systemctl", "--user", "kill", "--signal=SIGKILL", unit],
                 ["systemctl", "--user", "stop", unit]):
        try:
            subprocess.run(argv, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def _kill_tree(pgid: int, unit: str, *, grace_s: float = KILL_GRACE_S) -> None:
    """Take down one tree: politely, then not.

    Order matters. The process group gets a chance to shut down cleanly first,
    because a test runner killed mid-write leaves output we would like to read.
    The cgroup kill is unconditional and last, and it is the one that actually
    guarantees the tree is gone.
    """
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    if grace_s:
        time.sleep(grace_s)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    _kill_scope(unit)


def _reap_all() -> None:
    """Kill every tree still registered. Runs on our way out, however we go."""
    with _live_lock:
        trees = list(_live.items())
        _live.clear()
    if not trees:
        return
    logger.warning("reaping %d subprocess tree(s) on exit; they would "
                   "otherwise be reparented to init and keep running",
                   len(trees))
    for pgid, unit in trees:
        # No grace on this path: we are leaving, and there is nobody left to
        # read whatever a polite shutdown would have written.
        _kill_tree(pgid, unit, grace_s=0)


def _install_handlers() -> None:
    """Reap on normal exit and on the signals a CI job actually dies from.

    `atexit` alone is not enough: a cancelled Actions run or a `pm2 stop`
    arrives as SIGTERM, which by default terminates the process without
    running atexit hooks. We chain to the previous handler so this stays
    composable with whatever else the process installed.
    """
    global _handlers_installed
    if _handlers_installed:
        return
    _handlers_installed = True

    atexit.register(_reap_all)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            previous = signal.getsignal(sig)
        except (ValueError, OSError):
            continue

        def handler(signum, frame, _previous=previous, _sig=sig):
            _reap_all()
            if callable(_previous) and _previous not in (
                    signal.SIG_IGN, signal.SIG_DFL):
                return _previous(signum, frame)
            # Re-raise with the default disposition so the exit status still
            # says "died of this signal" rather than a plain 0.
            signal.signal(_sig, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            # Not the main thread, or a platform without it. The atexit hook
            # still stands.
            pass


# ── cgroup availability ──────────────────────────────────────────────────────

def scope_available() -> bool:
    """Whether we can put a child in a systemd scope with real limits.

    Probed by actually creating one, once, and cached. A capability this
    important must not be inferred from the presence of a binary: a headless
    runner can have `systemd-run` on PATH and no user D-Bus session to talk
    to, and the failure only shows up at spawn time.
    """
    global _scope_ok
    if _scope_ok is not None:
        return _scope_ok
    if FORCE_NO_CGROUP or not shutil.which("systemd-run"):
        _scope_ok = False
    else:
        try:
            probe = subprocess.run(
                ["systemd-run", "--user", "--scope", "-q", "--collect",
                 "-p", "MemoryMax=64M", "--", "true"],
                capture_output=True, timeout=30, check=False)
            _scope_ok = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _scope_ok = False

    if not _scope_ok:
        logger.warning(
            "no systemd user scope available — subprocess trees will get a "
            "process-group kill and PDEATHSIG, but NO memory ceiling and no "
            "wall clock that survives this process dying. A runaway child can "
            "take the host down. Set up a user D-Bus session, or run the "
            "pipeline under a container with its own limits.")
    return _scope_ok


def _preexec() -> None:
    """Runs in the child, between fork and exec.

    `start_new_session=True` already gives us the new session and process
    group; this adds the parent-death signal, which is the only reaping that
    works if we are SIGKILLed and never run a handler. It survives `execve`,
    so it still covers the workload after `systemd-run` execs into it.
    """
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
    except Exception:
        # Best-effort by construction. The cgroup is the real guarantee.
        pass

    # Guard the race: if the parent died between fork and prctl, PDEATHSIG can
    # never fire because the death already happened. `getppid() == 1` means we
    # have been reparented already, so leave now rather than become the orphan
    # this module exists to prevent.
    if os.getppid() == 1:
        os._exit(0)


def _looks_oom_killed(rc: Optional[int], unit: str) -> bool:
    """Whether `rc` from a scoped run means "the memory ceiling killed it".

    `-9` when we spawned the binary directly, `137` when something in between
    (a shell, `systemd-run`) reports the signal as an exit status. Both were
    observed reproducing the original incident: the runaway typecheck came back
    as `returncode=-9` with `out_of_memory` set.

    Only meaningful when a scope was used — without `MemoryMax` there is no
    ceiling to have hit, and a bare SIGKILL then means something else killed
    the job (an operator, a supervisor) which is not the same story to tell.

    Split out from `run` so it can be tested without OOM-killing a process on
    every suite run. Whether the kernel enforces `memory.max` is the kernel's
    contract; what belongs to us is putting the limit on the right cgroup —
    asserted directly in the tests — and reading the result correctly, which
    is this.
    """
    return bool(unit) and rc in (-signal.SIGKILL, 137)


def _resolve(program: str, env: Optional[dict]) -> str:
    """Absolute path for `program`, or `FileNotFoundError`.

    Done here rather than left to `exec` because with a scope the direct child
    is `systemd-run`, which exists — so a mistyped command would come back as
    an ordinary non-zero exit and read like a failing test run instead of a
    broken invocation. `agent.py` relies on this raising to say "claude not
    found on PATH".
    """
    if os.path.sep in program:
        if not os.path.exists(program):
            raise FileNotFoundError(errno.ENOENT, "no such file", program)
        return program
    found = shutil.which(program, path=(env or os.environ).get("PATH"))
    if not found:
        raise FileNotFoundError(errno.ENOENT, "not found on PATH", program)
    return found


def run(argv: Sequence[str], *, cwd: Optional[Path] = None,
        timeout: int = 600, env: Optional[dict] = None,
        stdin_text: Optional[str] = None,
        memory_max: str = "", label: str = "job") -> Ran:
    """Run `argv` so that neither a timeout nor our own death leaks processes.

    On timeout the whole tree is killed — process group first, then the cgroup
    by membership — and whatever it wrote before dying is returned. The partial
    output is the point: a timed-out test run usually says why in its last few
    lines, and throwing that away to report "timeout" is how a diagnosable
    failure becomes a mystery.
    """
    _install_handlers()

    args = [str(a) for a in argv]
    if not args:
        raise ValueError("argv is empty")
    args[0] = _resolve(args[0], env)

    unit = ""
    launch = args
    spawn_env = env
    if scope_available():
        # Lend systemd-run the bus variables if the caller's environment does
        # not have them, then strip them back off the workload. Without this,
        # any caller passing a scrubbed env (the agent, exactly the thing that
        # most needs containing) fails to spawn at all.
        if env is not None:
            lent = {k: os.environ[k] for k in _BUS_VARS
                    if k in os.environ and k not in env}
            if lent:
                spawn_env = {**env, **lent}
                strip: list[str] = []
                for k in lent:
                    strip += ["-u", k]
                args = [_resolve("env", spawn_env), *strip, *args]

        unit = f"taskauto-{label}-{uuid.uuid4().hex[:8]}.scope"
        launch = [
            "systemd-run", "--user", "--scope", "-q", "--collect",
            f"--unit={unit}",
            "-p", f"MemoryMax={memory_max or DEFAULT_MEMORY_MAX}",
            "-p", "MemorySwapMax=0",
            "-p", f"RuntimeMaxSec={int(timeout) + RUNTIME_MAX_SLACK_S}",
            "--", *args,
        ]

    try:
        proc = subprocess.Popen(
            launch, cwd=str(cwd) if cwd else None, env=spawn_env,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=True, preexec_fn=_preexec)
    except OSError as e:
        return Ran(False, "", f"could not spawn {args[0]}: {e}")

    # The child is a session leader, so its pid IS the process group id, and
    # every descendant that does not deliberately leave inherits it.
    pgid = proc.pid
    _register(pgid, unit)

    try:
        out, err = proc.communicate(input=stdin_text, timeout=timeout)
        rc = proc.returncode
        oom = _looks_oom_killed(rc, unit)
        if oom:
            logger.error("%s exceeded its %s memory ceiling and was killed "
                         "(this is the containment working, not a pipeline "
                         "bug)", label, memory_max or DEFAULT_MEMORY_MAX)
        return Ran(rc == 0, out or "", err or "", out_of_memory=oom,
                   returncode=rc)
    except subprocess.TimeoutExpired as e:
        logger.warning("%s exceeded %ss; killing the whole tree", label, timeout)
        _kill_tree(pgid, unit)
        try:
            out, err = proc.communicate(timeout=30)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            out = _text(getattr(e, "stdout", ""))
            err = _text(getattr(e, "stderr", ""))
        return Ran(False, out or "", (err or "") + f"\ntimed out after {timeout}s",
                   timed_out=True, returncode=proc.returncode)
    finally:
        _forget(pgid)
        # Belt and braces. If communicate() raised something we did not
        # anticipate, the tree is still ours to clean up.
        if proc.poll() is None:
            _kill_tree(pgid, unit, grace_s=0)


def _text(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v or ""
