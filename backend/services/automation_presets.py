"""The lane contracts this repo publishes, as a document a machine can fetch.

hadoku-task can turn a board into an automation board from a preset. Until now
the preset got there by a human pasting our activation JSON into their UI, which
makes the human the sync mechanism: the moment we rename a lane, every pasted
copy is stale and nobody finds out until a task lands in a lane that no longer
exists. So they fetch the contract instead of storing a copy of it, and this is
the half that serves it.

**The file on disk is the source of truth, not a copy of it.**
`docs/hadoku-task-automation/schemas/*.json` is already what we hand to
`activate-automation` and what `scripts/taskauto_smoke.py` diffs a live board
against. Serving those same bytes is the whole point — a second hand-maintained
copy in Python would be the pasted JSON problem again, one layer down.

Two things happen on the way out:

  - **`repo` is stripped.** It is per-board (`WolffM/<repo>` in the file is a
    placeholder), and a preset is a lane vocabulary, not a board. hadoku-task
    ignores it anyway; publishing a placeholder repo in a public document is
    just noise that reads like a real value.
  - **Every preset is validated with `validate_lane_set`**, a port of the
    `validateLaneSet` that guards activation on their side. They run it too and
    drop what fails — running it here as well means we find out at test time
    that we broke our own contract, instead of finding out because a picker
    quietly stopped offering us.

The ETag is a strong validator over the exact bytes served, so an unchanged
contract costs a 304 rather than a re-download and re-parse.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the activation payloads live. One file per named config; today that is
#: `autoland-v1.json` alone. crimson-kitty, the other pipeline, is not
#: board-driven and has no lane vocabulary to publish.
SCHEMA_DIR = (Path(__file__).resolve().parents[2]
              / "docs" / "hadoku-task-automation" / "schemas")

#: Fields that describe a *board*, not a lane vocabulary. Dropped on the way out.
_BOARD_SPECIFIC_KEYS = ("repo",)


class PresetInvalid(ValueError):
    """A payload on disk isn't a lane set anyone should be offered."""


@dataclass(frozen=True)
class PresetDocument:
    """The rendered response and its validator, cached together.

    `body` is the exact bytes served, and `etag` hashes those bytes — the two
    must not be able to drift, which is why they're built and cached as a pair.
    """

    body: bytes
    etag: str
    count: int


def validate_lane_set(lanes: Any) -> None:
    """Reject a lane set hadoku-task's `validateLaneSet` would reject.

    Their checks, in their order, plus one of ours: `order` must be unique.
    They don't require it — a lane set with two lanes at order 0 activates
    fine — but the resulting column order is whatever the sort happens to do
    with the tie, so it is a real defect in a document whose entire job is to
    say what order the lanes go in.

    Note `isinstance(order, bool)`: in Python `True` is an `int`, so the
    numeric check admits it without that guard. In TypeScript `typeof true`
    is `"boolean"` and their check rejects it for free.
    """
    if not isinstance(lanes, list) or not lanes:
        raise PresetInvalid("`lanes` must be a non-empty array")

    seen_tags: set[str] = set()
    orders: dict[float, str] = {}
    for lane in lanes:
        if not isinstance(lane, dict):
            raise PresetInvalid("every lane must be an object")

        tag = lane.get("tag")
        if not isinstance(tag, str) or not tag:
            raise PresetInvalid("every lane needs a non-empty string `tag`")
        if any(ch.isspace() for ch in tag):
            raise PresetInvalid(f'lane tag "{tag}" may not contain whitespace')
        if tag in seen_tags:
            raise PresetInvalid(f'duplicate lane tag "{tag}"')
        seen_tags.add(tag)

        label = lane.get("label")
        if not isinstance(label, str) or not label:
            raise PresetInvalid(f'lane "{tag}" needs a non-empty string `label`')

        order = lane.get("order")
        if isinstance(order, bool) or not isinstance(order, (int, float)) \
                or not math.isfinite(order):
            raise PresetInvalid(f'lane "{tag}" needs a numeric `order`')
        if order in orders:
            raise PresetInvalid(
                f'lanes "{orders[order]}" and "{tag}" share `order` {order}')
        orders[order] = tag

        if lane.get("editableBy") not in ("user", "agent"):
            raise PresetInvalid(
                f'lane "{tag}" `editableBy` must be "user" or "agent"')


def _to_preset(raw: Any, source: str) -> dict[str, Any]:
    """One on-disk payload, checked and stripped of board-specific fields."""
    if not isinstance(raw, dict):
        raise PresetInvalid(f"{source}: payload must be a JSON object")
    if not isinstance(raw.get("schemaId"), str) or not raw["schemaId"]:
        raise PresetInvalid(f"{source}: `schemaId` must be a non-empty string")
    validate_lane_set(raw.get("lanes"))
    return {k: v for k, v in raw.items() if k not in _BOARD_SPECIFIC_KEYS}


def _render(payloads: list[dict[str, Any]]) -> PresetDocument:
    body = (json.dumps({"presets": payloads}, indent=2,
                       ensure_ascii=False) + "\n").encode("utf-8")
    return PresetDocument(body=body,
                          etag=hashlib.sha256(body).hexdigest(),
                          count=len(payloads))


def _schema_files() -> list[Path]:
    if not SCHEMA_DIR.is_dir():
        return []
    return sorted(SCHEMA_DIR.glob("*.json"))


def _fingerprint(paths: list[Path]) -> tuple:
    """Cheap "has anything changed" key: path, mtime and size of each file.

    A deploy restarts the process so a plain load-once would do in production,
    but re-reading on change means editing a schema locally shows up without a
    restart, and it costs one `stat` per file per request.
    """
    out = []
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            continue
        out.append((str(path), st.st_mtime_ns, st.st_size))
    return tuple(out)


_lock = threading.Lock()
_cache: tuple[tuple, PresetDocument] | None = None


def load_presets() -> PresetDocument:
    """Every publishable preset, rendered and hashed.

    A file that fails validation is dropped and logged rather than taken down
    with the others — one broken preset should not blank out the good ones. If
    *nothing* survives the caller has nothing honest to serve; that's a
    `PresetInvalid`, not an empty document, because an empty `presets` array
    reads as "this provider has no lane sets" rather than "this provider is
    broken".
    """
    global _cache

    paths = _schema_files()
    fingerprint = _fingerprint(paths)

    with _lock:
        if _cache is not None and _cache[0] == fingerprint:
            return _cache[1]

        payloads: list[dict[str, Any]] = []
        for path in paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                payloads.append(_to_preset(raw, path.name))
            except (OSError, json.JSONDecodeError, PresetInvalid) as exc:
                logger.error("automation preset %s is not publishable: %s",
                             path.name, exc)

        if not payloads:
            raise PresetInvalid(
                f"no publishable lane sets in {SCHEMA_DIR}"
                f" ({len(paths)} file(s) inspected)")

        document = _render(payloads)
        _cache = (fingerprint, document)
        return document
