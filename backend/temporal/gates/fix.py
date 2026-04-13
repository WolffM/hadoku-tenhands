"""Gates that fire after the `fixed` state transition.

- diff_non_empty (mechanical) — kills empty-PR class. **Highest-ROI gate
  in the entire system** — would have killed 21% of jade-hare's bad
  upstream PRs by itself.
- relevance (judge) — kills the unrelated-cleanup class
  (markitdown unrelated imports).

Not yet implemented. Pseudocode:

    from . import gate, GateResult, Pass, Fail, Defer

    @gate(after="fixed", kind="mechanical")
    def diff_non_empty(evidence_dir: str) -> GateResult:
        ev = EvidenceStore.from_path(evidence_dir)
        diff = ev.read_text("05-fixed/diff.patch", default="")
        shas = ev.read_lines("05-fixed/commit_shas.txt")

        if not diff.strip():
            return Fail("diff_non_empty",
                        "diff is empty — no commits ahead of base")
        if not shas:
            return Fail("diff_non_empty", "no commit SHAs recorded")
        if len(diff) < 50:
            return Fail("diff_non_empty",
                        f"diff suspiciously short ({len(diff)} bytes)")
        return Pass("diff_non_empty")

    @gate(after="fixed", kind="judge")
    def relevance(evidence_dir: str) -> GateResult:
        ev = EvidenceStore.from_path(evidence_dir)
        files      = ev.read_lines("05-fixed/files_touched.txt")
        issue_body = ev.read_json("01-eligible/issue_brief.json")["issue"]["body"]

        from ..judge import score
        s, reasoning = score(
            payload={"issue_body": issue_body[:1000], "files_touched": files},
            rubric="relevance_v1",
        )
        if s < 0.6:
            return Defer("relevance",
                         f"low relevance (score={s:.2f})",
                         evidence_data={"score": s, "reasoning": reasoning})
        return Pass("relevance", score=s)
"""
