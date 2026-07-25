"""environment_works gate — runs after `environment_ready` state.

Reads the health.json the environment activity wrote. Fails if the repo
couldn't clone, install, or start its dev server (where applicable).

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

from . import CRIMSON_KITTY, Fail, GateResult, IssueRef, Pass, gate


@gate(pipeline=CRIMSON_KITTY, after="environment_ready", kind="mechanical")
def environment_works(issue: IssueRef, evidence) -> GateResult:
    if not evidence.exists("03-environment/health.json"):
        return Fail("03-environment/health.json missing")

    health = evidence.read_json("03-environment/health.json")
    if not isinstance(health, dict):
        return Fail(f"health.json is not an object: {type(health).__name__}")

    if not health.get("installable"):
        return Fail(
            "dependencies failed to install",
            evidence_data={"install_log": "03-environment/install_log.txt"},
        )

    # Check that the install actually did something — a no-op install
    # (empty stdout + stderr) means the environment wasn't really set up.
    if evidence.exists("03-environment/install_log.txt"):
        log = evidence.read_text("03-environment/install_log.txt")
        # Strip the header lines the activity always writes
        lines = [
            l for l in log.splitlines()
            if l.strip() and not l.startswith(("returncode=", "success=", "--- "))
        ]
        if not lines:
            return Fail(
                "install produced no output - environment not actually set up",
                evidence_data={"install_log_lines": 0},
            )

    # runnable is optional — many libraries don't have a dev server
    if "runnable" in health and health.get("runnable") is False:
        return Fail(
            "dev server failed to start",
            evidence_data={"dev_server_log": "03-environment/dev_server_log.txt"},
        )

    return Pass()
