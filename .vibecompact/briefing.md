# vibeCompact — agent briefing

Anchor: `c30a2d47f010` (2026-08-18). Generated with the audit report; findings below are corroborated by ≥2 independent lanes unless marked otherwise.

## Ground rules

- Fixes need no ceremony: land a commit touching a flagged file and the next audit stamps it `fixed` automatically. Partial progress shows as **improving**.
- Findings you judge wrong get verdicts, not workarounds — the commands are attached to each finding. Verdicts are maintainer decisions; confirm with the human before filing one.
- Do not delete anything without verifying reachability yourself first: string references, dynamic imports, runner and workflow configs.
- Coverage warning: 1 of 6 planned lanes unavailable or degraded (deadcode). Corroboration was weakened this run — an empty corroborated section is a coverage statement, and single-lane findings deserve more weight than usual.

## Corroborated work items

None pass the ≥2-lane gate this run.

## Single-lane findings (one signal each — weigh accordingly)

Each has a full evidence package in `.vibecompact/findings/`.

- `backend/temporal/activities/submission.py` — size: 857 code lines (tier 2) → `.vibecompact/findings/backend__temporal__activities__submission.py.md`
- `frontend/src/components/temporal/EvidencePreview.tsx` — arrival → `.vibecompact/findings/frontend__src__components__temporal__EvidencePreview.tsx.md`
- `frontend/src/api/client.ts` — arrival → `.vibecompact/findings/frontend__src__api__client.ts.md`
- `frontend/e2e/prod/oss-recon.spec.ts` — size: 1011 code lines (tier 2) → `.vibecompact/findings/frontend__e2e__prod__oss-recon.spec.ts.md`
- `frontend/src/hooks/index.ts` — arrival → `.vibecompact/findings/frontend__src__hooks__index.ts.md`
- `backend/tests/temporal/test_workflows.py` — size: 778 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_workflows.py.md`
- `backend/tests/temporal/test_gates.py` — size: 747 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_gates.py.md`
- `frontend/src/styles/retro.css` — size: 768 code lines (tier 1) → `.vibecompact/findings/frontend__src__styles__retro.css.md`
- `backend/temporal/workflows/issue_workflow.py` — size: 575 code lines (tier 1) → `.vibecompact/findings/backend__temporal__workflows__issue_workflow.py.md`
- `backend/helpers/report_generator.py` — size: 558 code lines (tier 1) → `.vibecompact/findings/backend__helpers__report_generator.py.md`
- `backend/tests/temporal/test_temporal_routes.py` — size: 558 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_temporal_routes.py.md`
- `scripts/render_actionability_html.py` — size: 551 code lines (tier 1) → `.vibecompact/findings/scripts__render_actionability_html.py.md`
- `backend/routes/taskauto_routes.py` — size: 537 code lines (tier 1) → `.vibecompact/findings/backend__routes__taskauto_routes.py.md`
- `scripts/copilot-sessions.py` — size: 517 code lines (tier 1) → `.vibecompact/findings/scripts__copilot-sessions.py.md`
- `backend/services/oss_fork.py` — size: 500 code lines (tier 1) → `.vibecompact/findings/backend__services__oss_fork.py.md`
- `scripts/retro_report.py` — size: 492 code lines (tier 1) → `.vibecompact/findings/scripts__retro_report.py.md`
- `backend/routes/temporal_routes.py` — size: 490 code lines (tier 1) → `.vibecompact/findings/backend__routes__temporal_routes.py.md`
- `backend/tests/test_task_board.py` — size: 488 code lines (tier 1) → `.vibecompact/findings/backend__tests__test_task_board.py.md`
- `frontend/src/store/pipelineStore.ts` — arrival → `.vibecompact/findings/frontend__src__store__pipelineStore.ts.md`
- `frontend/src/components/vibecheck/Stage4Review.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage4Review.tsx.md`
- `frontend/src/api/endpoints.ts` — arrival → `.vibecompact/findings/frontend__src__api__endpoints.ts.md`
- `frontend/src/components/oss/ForkAssignPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__ForkAssignPanel.tsx.md`
- `frontend/src/components/retro/IssueRetroCard.tsx` — arrival → `.vibecompact/findings/frontend__src__components__retro__IssueRetroCard.tsx.md`
- `frontend/src/components/vibecheck/Stage2Run.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage2Run.tsx.md`
- `frontend/src/components/vibecheck/Stage3Assign.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage3Assign.tsx.md`
- `frontend/src/views/HealthCheckView.tsx` — arrival → `.vibecompact/findings/frontend__src__views__HealthCheckView.tsx.md`
- `frontend/src/views/TaskAutoView.tsx` — arrival → `.vibecompact/findings/frontend__src__views__TaskAutoView.tsx.md`
- `frontend/src/components/oss/PipelineRunsPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__PipelineRunsPanel.tsx.md`
- `frontend/src/components/oss/RepoHealthPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__RepoHealthPanel.tsx.md`
- `frontend/src/components/review/PRModal.tsx` — arrival → `.vibecompact/findings/frontend__src__components__review__PRModal.tsx.md`

_Cap: 70 more single-lane firings not packaged this run (per-lane cap 15: arrival +56, size +14). They still fire in the machine data._

## Machine data

Full lane entries, clone partners, scores, and ledger state: `.vibecompact/audit.json` on the data branch, `.vibecompact/out/audit.json` in a local run.
