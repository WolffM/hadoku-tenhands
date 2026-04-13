"""Eligibility activity: fetch dossier, scan CONTRIBUTING.md, decide.

Reuses:
    backend.services.oss_service._call_aggregator
    backend.helpers.validation.to_aggregator_slug
    backend.services.cache (for repeated dossier reads)

Writes evidence:
    01-eligible/dossier.json
    01-eligible/issue_brief.json
    01-eligible/contributing_check.json
    01-eligible/decision.json

Not yet implemented. Stub for design review. Pseudocode:

    @activity.defn
    async def check_eligibility(issue_ref: IssueRef, evidence_dir: str) -> None:
        ev = EvidenceStore.from_path(evidence_dir)
        slug = to_aggregator_slug(issue_ref.upstream_slug)

        dossier = _call_aggregator(f"/recon/{slug}/dossier")
        brief   = _call_aggregator(f"/recon/{slug}/issue-brief/{issue_ref.upstream_number}")
        ev.write_json("01-eligible/dossier.json", dossier)
        ev.write_json("01-eligible/issue_brief.json", brief)

        contrib = scan_contributing_md(dossier)  # see open Q3 — may move to aggregator
        ev.write_json("01-eligible/contributing_check.json", contrib)

        decision = {"passed": True, "reason": "all checks ok"}
        ev.write_json("01-eligible/decision.json", decision)
"""
