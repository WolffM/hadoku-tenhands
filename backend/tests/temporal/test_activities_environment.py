"""the environment activity

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

def test_setup_environment_pass(ev, tmp_path):
    from temporal.activities.environment import setup_environment

    def fake_runner(cmd, cwd, timeout):
        return {"success": True, "output": "installed", "error": "", "returncode": 0}

    setup_environment(
        fork_slug="WolffM/markitdown",
        branch_name="b",
        workdir=str(tmp_path),
        install_cmd=["pip", "install", "-e", "."],
        evidence=ev,
        runner=fake_runner,
    )
    health = ev.read_json("03-environment/health.json")
    assert health == {"installable": True}
    assert ev.exists("03-environment/install_log.txt")


def test_setup_environment_records_install_failure(ev, tmp_path):
    from temporal.activities.environment import setup_environment

    def fake_runner(cmd, cwd, timeout):
        return {"success": False, "output": "", "error": "missing dep", "returncode": 1}

    setup_environment(
        "WolffM/markitdown", "b", str(tmp_path), ["pip", "install", "-e", "."], ev,
        runner=fake_runner,
    )
    assert ev.read_json("03-environment/health.json")["installable"] is False


def test_setup_environment_with_dev_server(ev, tmp_path):
    from temporal.activities.environment import setup_environment

    def fake_runner(cmd, cwd, timeout):
        return {"success": True, "output": "", "error": "", "returncode": 0}

    setup_environment(
        "WolffM/x", "b", str(tmp_path), ["pip", "install"], ev,
        dev_server_cmd=["python", "-m", "http.server"],
        runner=fake_runner,
    )
    health = ev.read_json("03-environment/health.json")
    assert health == {"installable": True, "runnable": True}
