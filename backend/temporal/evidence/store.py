"""Evidence store: per-issue artifact directories.

Each issue has a directory under `state/{batch}/{slug-encoded}-{number}/`
that holds every artifact the pipeline produces. Artifacts are plain files
(json, txt, png, patch, jsonl). The retro tool reads from them directly —
no API round-trip needed.

See docs/crimson-kitty/state-machine.md#evidence-store-layout for the full
directory schema.

Phase 1A.5.

The class is intentionally thin — it's just typed file/dir helpers plus
JSONL append. No business logic. Concurrency safety: JSONL appends use
O_APPEND so concurrent appends from multiple threads are atomic at the
line level on POSIX.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode_slug(slug: str) -> str:
    """Encode `owner/repo` to `owner__repo` so it's a valid path component."""
    return slug.replace("/", "__")


class EvidenceStore:
    """Per-issue artifact store rooted at `{root}/`.

    Construct directly with a path, or via `for_issue(batch, slug, number)`
    to land in the canonical layout.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Per-instance lock for JSONL appends. Cheap and prevents intra-process
        # interleaving on platforms where O_APPEND atomicity isn't guaranteed.
        self._jsonl_lock = threading.Lock()

    @classmethod
    def for_issue(cls, batch: str, slug: str, number: int, base: Path | str = "state") -> "EvidenceStore":
        encoded = _encode_slug(slug)
        return cls(Path(base) / batch / f"{encoded}-{number}")

    # ── path helpers ──────────────────────────────────────────────────────

    def path(self, rel: str) -> Path:
        return self.root / rel

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    def _ensure_parent(self, rel: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ── writes ────────────────────────────────────────────────────────────

    def write_text(self, rel: str, text: str) -> None:
        p = self._ensure_parent(rel)
        p.write_text(text, encoding="utf-8")

    def write_json(self, rel: str, data: Any, *, indent: int = 2) -> None:
        p = self._ensure_parent(rel)
        p.write_text(
            json.dumps(data, indent=indent, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_bytes(self, rel: str, data: bytes) -> None:
        p = self._ensure_parent(rel)
        p.write_bytes(data)

    def append_jsonl(self, rel: str, record: dict) -> None:
        p = self._ensure_parent(rel)
        line = json.dumps(record, sort_keys=True) + "\n"
        with self._jsonl_lock:
            # O_APPEND makes the write atomic w.r.t. other processes too.
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)

    # ── reads ─────────────────────────────────────────────────────────────

    def read_text(self, rel: str, default: str | None = None) -> str:
        p = self.root / rel
        if not p.exists():
            if default is not None:
                return default
            raise FileNotFoundError(p)
        return p.read_text(encoding="utf-8")

    def read_json(self, rel: str) -> Any:
        return json.loads(self.read_text(rel))

    def read_lines(self, rel: str) -> list[str]:
        text = self.read_text(rel)
        return text.splitlines()

    def read_jsonl(self, rel: str) -> list[dict]:
        if not (self.root / rel).exists():
            return []
        return [json.loads(line) for line in self.read_lines(rel) if line.strip()]

    # ── domain-specific recorders ─────────────────────────────────────────

    def record_transition(
        self,
        from_state: str,
        to_state: str,
        reason: str,
        decided_by: str,
    ) -> None:
        """Append one record to transitions.jsonl."""
        self.append_jsonl("transitions.jsonl", {
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "decided_by": decided_by,
            "ts": _now_iso(),
        })

    def record_gate(
        self,
        gate_name: str,
        verdict: str,
        reason: str = "",
        evidence_data: dict | None = None,
    ) -> None:
        """Append one record to gates.jsonl."""
        self.append_jsonl("gates.jsonl", {
            "gate": gate_name,
            "verdict": verdict,
            "reason": reason,
            "evidence_data": evidence_data,
            "ts": _now_iso(),
        })
