"""Tests for the subprocess containment.

These spawn real processes on purpose. The bug this module exists to prevent is
entirely about what the *kernel* does with process groups, orphans and cgroups,
so a mocked subprocess would assert nothing worth knowing — the original outage
happened in code whose unit tests were all green.

Kept cheap: `sleep`, a few seconds, and a memory hog that allocates in Python
rather than a real typechecker.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from temporal.taskauto import proc

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _kill_and_report(marker: str) -> list[int]:
    """PIDs still matching `marker`, killed so a failure leaves no debris."""
    out = subprocess.run(["pgrep", "-f", marker], capture_output=True,
                         text=True, check=False).stdout
    pids = [int(p) for p in out.split() if int(p) != os.getpid()]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return pids


# ── the actual bug ───────────────────────────────────────────────────────────

def test_timeout_kills_grandchildren_not_just_the_direct_child():
    """The 2026-07-29 outage in one test.

    `subprocess.run(timeout=)` would kill the shell and leave the `sleep`
    running, reparented to init. A grandchild is the normal case here, not an
    exotic one: the agent's runaway typecheck was four levels down.
    """
    marker = "taskauto-orphan-probe-9x1"
    res = proc.run(["sh", "-c", f"sh -c 'exec sleep 120 # {marker}' & wait"],
                   timeout=3, label="test")

    assert res.timed_out
    time.sleep(1)                      # let the kill land
    assert not _kill_and_report(marker), "grandchild survived the timeout"


def test_partial_output_survives_a_timeout():
    """A timed-out suite names the hanging test in its last lines.

    Returning a bare "timeout" and discarding that is how a diagnosable
    failure becomes a mystery, so the output has to come back.
    """
    res = proc.run(["sh", "-c", "echo where-it-hung; sleep 120"],
                   timeout=3, label="test")
    assert res.timed_out
    assert "where-it-hung" in res.out


def test_children_die_when_the_parent_exits():
    """No orphans, which is the property the runner actually needed.

    Runs a *separate* Python process that starts a long child through
    `proc.run` and then exits without waiting — exactly what
    `run_taskauto.py` did. The child must not outlive it.
    """
    marker = "taskauto-parent-exit-probe-9x2"
    script = textwrap.dedent(f"""
        import sys, threading, time
        sys.path.insert(0, {BACKEND!r})
        from temporal.taskauto import proc
        # Start it on a daemon thread and leave without joining, so the
        # interpreter exits while the child is still running.
        threading.Thread(
            target=proc.run,
            args=(["sh", "-c", "exec sleep 120 # {marker}"],),
            kwargs=dict(timeout=120, label="test"),
            daemon=True).start()
        time.sleep(2)
    """)
    subprocess.run([sys.executable, "-c", script], timeout=90, check=False,
                   capture_output=True)
    time.sleep(2)

    assert not _kill_and_report(marker), (
        "child outlived its parent and was reparented to init")


# ── the memory ceiling ───────────────────────────────────────────────────────

@pytest.mark.skipif(not proc.scope_available(),
                    reason="no systemd user scope on this host")
def test_the_memory_limits_actually_land_on_the_workload_cgroup():
    """The limits reach the cgroup the workload is really running in.

    Asserted by having the workload read its *own* `memory.max` and
    `memory.swap.max` out of cgroupfs, rather than by triggering an OOM kill.
    Two reasons that is the better test. It is silent — a real OOM kill writes
    to the kernel log and fires a desktop notification, and a suite that does
    that on every run trains everyone to ignore the one that matters. And it
    checks the half we are actually responsible for: that our `systemd-run`
    invocation puts the right numbers on the right cgroup. That the kernel then
    enforces them is the kernel's business, and is covered by the opt-in test
    below.
    """
    read_own_limits = (
        'g=$(awk -F: \'/^0::/{print $3}\' /proc/self/cgroup); '
        'echo "max=$(cat /sys/fs/cgroup$g/memory.max) '
        'swap=$(cat /sys/fs/cgroup$g/memory.swap.max)"')
    res = proc.run(["sh", "-c", read_own_limits],
                   timeout=60, memory_max="256M", label="test")

    assert res.ok, res.err[:300]
    assert "max=268435456" in res.out, f"MemoryMax did not land: {res.out}"
    # The incident let swap absorb 40 GB, which is what turned a job that
    # should have died into an outage. Zero, not "some".
    assert "swap=0" in res.out, f"MemorySwapMax did not land: {res.out}"


@pytest.mark.skipif(
    os.environ.get("TASKAUTO_TEST_OOM", "") != "1",
    reason="deliberately OOM-kills a process; set TASKAUTO_TEST_OOM=1 to run")
@pytest.mark.skipif(not proc.scope_available(),
                    reason="no systemd user scope on this host")
def test_memory_ceiling_kills_a_runaway_and_reports_it_as_such():
    """A pathological job dies instead of taking the box down.

    This is the guarantee that turns the original incident from a machine-wide
    outage into one failed tool call, so it is worth having — but it is opt-in.
    Running it writes a real `Killed process` line to the kernel log, and a
    suite that cries OOM on every run is a suite whose OOM reports nobody
    reads. Run it deliberately:

        TASKAUTO_TEST_OOM=1 pytest tests/taskauto/test_proc.py -k runaway
    """
    hog = ("a = bytearray()\n"
           "for _ in range(200): a.extend(bytearray(50_000_000))\n")
    res = proc.run([sys.executable, "-c", hog],
                   timeout=120, memory_max="256M", label="test")

    assert not res.ok
    assert res.out_of_memory, (
        f"expected the cgroup to kill it; rc={res.returncode} "
        f"err={res.err[:200]}")
    assert not res.timed_out, "it should die of the memory cap, not the clock"


@pytest.mark.skipif(not proc.scope_available(),
                    reason="no systemd user scope on this host")
def test_a_scrubbed_env_can_still_be_contained():
    """Regression: the agent passes an env with no D-Bus variables in it.

    `systemd-run --user` needs `XDG_RUNTIME_DIR` and
    `DBUS_SESSION_BUS_ADDRESS` to reach the user bus. The first version of this
    module passed the caller's env straight through, so every *agent*
    invocation — the one thing that most needs containing — died at spawn with
    "Failed to connect to user scope bus". Caught by a test, not in production,
    which is the whole reason this file spawns real processes.
    """
    res = proc.run(["sh", "-c", "echo contained-ok"],
                   timeout=60, env={"PATH": os.environ.get("PATH", "")},
                   label="test")
    assert res.ok, f"scrubbed env failed to spawn: {res.err[:300]}"
    assert "contained-ok" in res.out


@pytest.mark.skipif(not proc.scope_available(),
                    reason="no systemd user scope on this host")
def test_bus_variables_are_not_leaked_to_the_workload():
    """The bus handle is lent to systemd-run, never to the child.

    An untrusted agent with `DBUS_SESSION_BUS_ADDRESS` can talk to
    `systemd --user` and stop other units, so widening the allow-list in
    `agent.py` by a side effect of containment would be a real regression.
    """
    res = proc.run(
        ["sh", "-c", 'echo "bus=[${DBUS_SESSION_BUS_ADDRESS:-unset}] '
                     'xdg=[${XDG_RUNTIME_DIR:-unset}]"'],
        timeout=60, env={"PATH": os.environ.get("PATH", "")}, label="test")
    assert res.ok, res.err[:300]
    assert "bus=[unset]" in res.out, f"D-Bus address leaked: {res.out}"
    assert "xdg=[unset]" in res.out, f"XDG_RUNTIME_DIR leaked: {res.out}"


def test_env_is_replaced_not_merged():
    """The agent's scrubbed env is a containment boundary; verify it holds.

    A leak here would hand an untrusted agent the vault key.
    """
    os.environ["TASKAUTO_SECRET_PROBE"] = "must-not-appear"
    try:
        res = proc.run(["sh", "-c", 'echo "[${TASKAUTO_SECRET_PROBE:-unset}]"'],
                       timeout=60, env={"PATH": os.environ.get("PATH", "")},
                       label="test")
        assert "[unset]" in res.out
        assert "must-not-appear" not in res.out
    finally:
        os.environ.pop("TASKAUTO_SECRET_PROBE", None)


# ── ordinary behaviour must be unchanged ─────────────────────────────────────

def test_a_normal_command_is_unaffected_by_the_containment():
    res = proc.run(["sh", "-c", "echo out; echo err >&2; exit 0"],
                   timeout=30, label="test")
    assert res.ok
    assert "out" in res.out
    assert "err" in res.err
    assert not res.timed_out and not res.out_of_memory


def test_exit_status_and_stdin_pass_through():
    res = proc.run(["sh", "-c", 'read x; echo "got:$x"; exit 3'],
                   timeout=30, stdin_text="fed-in\n", label="test")
    assert not res.ok
    assert res.returncode == 3
    assert "got:fed-in" in res.out


def test_missing_binary_raises_rather_than_reporting_a_fake_failure():
    """A mistyped command must not read like a failing test run.

    Regression: with a scope the direct child is `systemd-run`, which exists,
    so the mistake came back as an ordinary non-zero exit. `agent.py` depends
    on this raising to report "claude not found on PATH".
    """
    with pytest.raises(FileNotFoundError):
        proc.run(["taskauto-definitely-not-a-real-binary-9x3"],
                 timeout=10, label="test")


def test_registry_is_empty_after_a_run():
    """A leaked registry entry would make the exit reaper kill a stranger's
    process group once the pid was recycled."""
    proc.run(["true"], timeout=30, label="test")
    assert not proc._live
