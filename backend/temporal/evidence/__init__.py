"""Evidence store: per-issue artifact directories.

Each issue has a directory under state/{batch}/{slug}-{issue}/ that
holds every artifact the pipeline produces. Artifacts are plain files
(JSON, txt, png, patch, jsonl). The retro tool reads from them
directly — no API round-trip needed.

See docs/crimson-kitty/state-machine.md#evidence-store-layout for the
directory schema.

Pseudocode:

    from pathlib import Path
    from typing import Any
    import json

    class EvidenceStore:
        def __init__(self, root: Path):
            self.root = root
            self.root.mkdir(parents=True, exist_ok=True)

        @classmethod
        def for_issue(cls, batch: str, slug: str, number: int) -> "EvidenceStore":
            encoded = slug.replace("/", "__")
            return cls(Path("state") / batch / f"{encoded}-{number}")

        def write_text(self, rel: str, text: str) -> None: ...
        def write_json(self, rel: str, data: Any) -> None: ...
        def write_bytes(self, rel: str, data: bytes) -> None: ...
        def read_text(self, rel: str, default: str | None = None) -> str: ...
        def read_json(self, rel: str) -> Any: ...
        def read_lines(self, rel: str) -> list[str]: ...
        def append_jsonl(self, rel: str, record: dict) -> None: ...
        def path(self, rel: str) -> Path: ...
        def exists(self, rel: str) -> bool: ...

        def record_transition(self, frm: str, to: str, reason: str,
                              decided_by: str) -> None:
            self.append_jsonl("transitions.jsonl", {
                "from": frm, "to": to, "reason": reason,
                "decided_by": decided_by, "ts": now_iso(),
            })

        def record_gate(self, gate_name: str, verdict: str,
                        reason: str, evidence_data: dict | None) -> None:
            self.append_jsonl("gates.jsonl", {
                "gate": gate_name, "verdict": verdict, "reason": reason,
                "evidence_data": evidence_data, "ts": now_iso(),
            })
"""
