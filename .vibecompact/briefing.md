# vibeCompact — agent briefing

Anchor: `e146e28dc6e4` (2026-09-17). Generated with the audit report; findings below are corroborated by ≥2 independent lanes unless marked otherwise.

## Ground rules

- Fixes need no ceremony: land a commit touching a flagged file and the next audit stamps it `fixed` automatically. Partial progress shows as **improving**.
- Findings you judge wrong get verdicts, not workarounds — the commands are attached to each finding. Verdicts are maintainer decisions; confirm with the human before filing one.
- Do not delete anything without verifying reachability yourself first: string references, dynamic imports, runner and workflow configs.

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
- `backend/tests/test_task_board.py` — size: 490 code lines (tier 1) → `.vibecompact/findings/backend__tests__test_task_board.py.md`
- `backend/routes/action_routes.py` — deadcode: unconsumed exports: unused function 'api_assign_copilot', unused function 'api_approve_pr', unused function 'api_mark_pr_ready' +2 → `.vibecompact/findings/backend__routes__action_routes.py.md`
- `backend/routes/automation_routes.py` — deadcode: unconsumed exports: unused attribute 'public', unused attribute 'max_age', unused function 'automation_openapi' → `.vibecompact/findings/backend__routes__automation_routes.py.md`
- `backend/routes/debug/assignment_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_assign_copilot', unused function 'api_oss_debug_score_issue' → `.vibecompact/findings/backend__routes__debug__assignment_routes.py.md`
- `backend/routes/debug/context_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_build_context', unused function 'api_oss_debug_create_context_issue' → `.vibecompact/findings/backend__routes__debug__context_routes.py.md`
- `backend/routes/debug/fork_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_fork_exists', unused function 'api_oss_debug_fork_repo', unused function 'api_oss_debug_fork_ready' +1 → `.vibecompact/findings/backend__routes__debug__fork_routes.py.md`
- `backend/routes/debug/health_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_gh_health', unused function 'api_oss_debug_aggregator_health', unused function 'api_oss_debug_state_dump' → `.vibecompact/findings/backend__routes__debug__health_routes.py.md`
- `backend/routes/debug/tracking_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_fork_pr_status', unused function 'api_oss_debug_poll_submitted_pr', unused function 'api_oss_debug_notification_preview' → `.vibecompact/findings/backend__routes__debug__tracking_routes.py.md`
- `backend/routes/health_routes.py` — deadcode: unconsumed exports: unused function 'api_healthcheck', unused function 'api_owner' → `.vibecompact/findings/backend__routes__health_routes.py.md`
- `backend/routes/workflow_routes.py` — deadcode: unconsumed exports: unused function 'api_install_vibecheck', unused function 'api_vibecheck_template', unused function 'api_update_vibecheck' +2 → `.vibecompact/findings/backend__routes__workflow_routes.py.md`
- `frontend/src/api/endpoints.ts` — arrival → `.vibecompact/findings/frontend__src__api__endpoints.ts.md`
- `frontend/src/components/vibecheck/Stage4Review.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage4Review.tsx.md`
- `frontend/src/store/pipelineStore.ts` — arrival → `.vibecompact/findings/frontend__src__store__pipelineStore.ts.md`
- `frontend/src/components/oss/ForkAssignPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__ForkAssignPanel.tsx.md`
- `frontend/src/components/retro/IssueRetroCard.tsx` — arrival → `.vibecompact/findings/frontend__src__components__retro__IssueRetroCard.tsx.md`
- `frontend/src/components/vibecheck/Stage2Run.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage2Run.tsx.md`
- `frontend/src/components/vibecheck/Stage3Assign.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage3Assign.tsx.md`
- `frontend/src/views/HealthCheckView.tsx` — arrival → `.vibecompact/findings/frontend__src__views__HealthCheckView.tsx.md`
- `frontend/src/views/TaskAutoView.tsx` — arrival → `.vibecompact/findings/frontend__src__views__TaskAutoView.tsx.md`
- `frontend/src/components/oss/PipelineRunsPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__PipelineRunsPanel.tsx.md`
- `frontend/src/components/oss/RepoHealthPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__RepoHealthPanel.tsx.md`
- `frontend/src/components/review/PRModal.tsx` — arrival → `.vibecompact/findings/frontend__src__components__review__PRModal.tsx.md`
- `backend/routes/oss_routes_stage5.py` — deadcode: unconsumed exports: unused function 'api_oss_stage5_submit', unused function 'api_oss_admin_archive_ready_to_submit', unused function 'api_oss_submit_to_origin' +2 → `.vibecompact/findings/backend__routes__oss_routes_stage5.py.md`

_Cap: 72 more single-lane firings not packaged this run (per-lane cap 15: arrival +57, size +15). They still fire in the machine data._

## Machine data

Full lane entries, clone partners, scores, and ledger state: `.vibecompact/audit.json` on the data branch, `.vibecompact/out/audit.json` in a local run.
