"""G6b — `dependencies_unchanged`.

The sibling of `protected_paths_untouched`, for the files that gate could
only ever answer wrongly. `package.json` and `pnpm-lock.yaml` sat on the
path deny-list under "new dependencies are new supply chain"; the risk is
real but the question was wrong, because in this ecosystem those files change
on nearly every task and almost never because a dependency was introduced.
See `temporal.taskauto.manifests` for the measurement and the rule.

This gate reads `05-fixed/diff.patch`, which the fix activity already writes
beside the `files_touched.txt` that G6 reads, so there is no new evidence to
produce. What it can see is strictly less than what the lander can — a hunk
routinely omits the enclosing `"scripts": {` — so it judges by value shape
and refuses anything unreadable. `Lander.preflight` runs the exact form of
the same rule against the checkout before anything is pushed; this is the
early, cheaper copy.

`allow-protected:` still applies, and is still only readable from the title
or the claim snapshot — see `task_text.extract_allow_protected`.
"""

from __future__ import annotations

from .protected_paths import _matches, protected_hits
from .. import TASK_AUTOMATION, Fail, GateResult, Pass, gate
from ...taskauto.manifests import classify_diff
from ...taskauto.task_text import extract_allow_protected


@gate(pipeline=TASK_AUTOMATION, after="fixed", kind="mechanical")
def dependencies_unchanged(task, evidence) -> GateResult:
    """Fail if a manifest change introduces a dependency, a lifecycle script,
    or anything else that widens what an install resolves or runs."""
    try:
        raw = evidence.read_text("05-fixed/files_touched.txt")
    except Exception as e:
        return Fail(f"could not read files_touched.txt: {type(e).__name__}: {e}")

    paths = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not paths:
        # G4 (diff_non_empty) owns the empty-diff case.
        return Pass("no files touched")

    policy = getattr(task, "policy", None)
    patterns = tuple(getattr(policy, "manifest_paths", ()) or ())
    hits = protected_hits(paths, patterns)
    if not hits:
        return Pass(f"{len(paths)} file(s), no manifests")

    # An explicit `allow-protected:` on a manifest is still an override. It is
    # how a genuine dependency addition lands: someone names the file in the
    # task title, having decided to accept it.
    allowed = extract_allow_protected(
        title=getattr(task, "title", "") or "",
        notes_at_claim=getattr(task, "notes_at_claim", "") or "",
    )
    to_judge = [p for p, _ in hits if not any(_matches(p, a) for a in allowed)]
    if not to_judge:
        return Pass(
            f"{len(hits)} manifest(s) touched, all authorised",
            evidence_data={"authorised": [p for p, _ in hits],
                           "allow_protected": allowed},
        )

    try:
        diff = evidence.read_text("05-fixed/diff.patch")
    except Exception as e:
        # A manifest changed and we cannot see how. That is the one thing this
        # gate exists to rule out, so it is a failure and never a pass.
        return Fail(
            f"{len(to_judge)} manifest(s) changed but the diff could not be "
            f"read: {type(e).__name__}: {e}",
            evidence_data={"manifests": to_judge},
        )

    verdict = classify_diff(diff, to_judge)
    if verdict.ok:
        return Pass(
            verdict.reason,
            evidence_data={"manifests": to_judge, "allow_protected": allowed,
                           **verdict.details},
        )
    return Fail(
        f"manifest change refused: {verdict.reason}",
        evidence_data={"manifests": to_judge,
                       "refusals": list(verdict.refusals),
                       "allow_protected": allowed,
                       **verdict.details},
    )
