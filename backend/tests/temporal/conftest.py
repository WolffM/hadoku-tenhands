"""Fixtures and helpers shared by the `test_activities_*` modules.

These were module-level in `test_activities.py` until it was split by
activity; a conftest is where they belong now that ten modules want them.
A module-local fixture of the same name still wins, so nothing here can
override what another test file already defines for itself.

`_conventions_envelope` is a plain helper rather than a fixture — it takes
keyword overrides and three of the modules build a different shape from it.
Imported the way this suite already imports shared helpers:
`from tests.temporal.conftest import _conventions_envelope`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temporal.agents import IssueRef
from temporal.evidence.store import EvidenceStore


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(
        fork_slug="WolffM/markitdown",
        upstream_slug="microsoft/markitdown",
        number=183,
    )


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


def _conventions_envelope(**overrides) -> dict:
    """Build a {success, data} envelope shaped like the aggregator's
    /recon/{slug}/contribution-conventions response."""
    refs_override = overrides.pop("references", None) or {}
    base = {
        "commit_style": "freeform",
        "title_prefix_pattern": None,
        "signoff_required": False,
        "body_structure": [],
        "references": {
            "close_keyword": "Fixes",
            "syntax": "Fixes #N",
            "in_body": True,
            **refs_override,
        },
        "evidence": {"source": "default", "raw_excerpt": None},
    }
    base.update(overrides)
    return {"success": True, "data": base}
