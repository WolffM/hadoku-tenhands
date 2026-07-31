"""The suite must not be able to reach a real notification sink.

Every other test here asserts something about the product. These assert
something about the *tests*: that running them cannot emit a real
notification, whatever credentials happen to be in the environment.

Worth its own file because the failure is invisible from inside a normal test
run. `_mirror_to_ledger` swallows its own exceptions by design (a notification
must never break the caller), so a leak produces no error, no failure and no
log — just fake events arriving in the sitrep, indistinguishable from real
ones. It went unnoticed until the suite was run with vault credentials loaded
and three "Upstream PR Submitted / Merged" events reached the live endpoint
for pull requests that do not exist.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import helpers.notifications as notifications


def test_every_outbound_sink_is_neutralised_by_the_autouse_fixture():
    """No notification escapes, with no per-test mocking at all.

    Deliberately calls the real `send_discord_notification` and lets it try
    both sinks. The autouse fixture in `conftest.py` is the only thing
    standing between this call and the network, which is exactly the
    configuration every other test in the suite runs under.
    """
    with patch.object(notifications, "requests") as fake_requests:
        notifications.send_discord_notification(
            "Upstream PR Merged!", "a fake event that must not leave this host",
            color=notifications.COLOR_SUCCESS)
        notifications.notify_upstream_submitted(
            "owner/repo", 1, "http://x", "a fake PR title")

    assert not fake_requests.post.called, (
        "a notification escaped the test suite: "
        f"{fake_requests.post.call_args_list}")


def test_the_module_constants_the_fixture_clears_are_the_ones_that_gate_sending():
    """Catch a new sink that nobody added to the fixture.

    The bug this file exists for was not a wrong assertion — it was a *new*
    destination added to `send_discord_notification` months after the fixture
    was written, gated on a different constant, which the fixture therefore did
    not clear. Nothing failed when that happened.

    So: find every module-level constant that looks like a destination or a
    credential, and require that the fixture has blanked it. A future sink
    fails here, at the point it is introduced, instead of leaking silently.
    """
    suspicious = {
        name: value
        for name, value in vars(notifications).items()
        if name.isupper()
        and isinstance(value, str)
        and (name.endswith(("_URL", "_KEY", "_TOKEN", "_WEBHOOK")))
    }
    # The fixture is autouse, so by the time this test body runs every gating
    # constant must already be falsy.
    still_live = {
        name: value[:12] + "…" for name, value in suspicious.items()
        if value and not name.startswith("MONITORING_")
    }
    assert not still_live, (
        f"these look like live notification sinks the autouse fixture in "
        f"conftest.py does not clear: {sorted(still_live)}. Add each to "
        f"`suppress_outbound_notifications`, or the suite can emit real "
        f"notifications when the matching credential is in the environment.")


def test_the_ledger_mirror_is_gated_on_the_constant_not_the_environment():
    """The gate has to be patchable, or the fixture cannot hold it.

    `_mirror_to_ledger` reads a module-level constant that `conftest` clears.
    If it were rewritten to read `os.environ` at call time, the fixture would
    silently stop working — the leak would come straight back, and again with
    nothing failing. This pins the shape.
    """
    source = inspect.getsource(notifications._mirror_to_ledger)
    assert "os.environ" not in source, (
        "_mirror_to_ledger must read the module-level HADOKU_SERVICE_KEY "
        "constant, not os.environ — conftest neutralises the constant, and "
        "reading the environment directly would bypass it")
