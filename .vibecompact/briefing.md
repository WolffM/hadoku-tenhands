# vibeCompact — agent briefing

Anchor: `fbc0b4f2aaa3` (2026-08-16). Generated with the audit report; findings below are corroborated by ≥2 independent lanes unless marked otherwise.

## Ground rules

- Fixes need no ceremony: land a commit touching a flagged file and the next audit stamps it `fixed` automatically. Partial progress shows as **improving**.
- Findings you judge wrong get verdicts, not workarounds — the commands are attached to each finding. Verdicts are maintainer decisions; confirm with the human before filing one.
- Do not delete anything without verifying reachability yourself first: string references, dynamic imports, runner and workflow configs.

## Corroborated work items (execution order: smallest blast radius first)

### 1. `frontend/src/components/common/Navigation.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__common__Navigation.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/common/Navigation.tsx" --reason "..."`

### 2. `frontend/src/components/common/ProgressLog.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__common__ProgressLog.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/common/ProgressLog.tsx" --reason "..."`

### 3. `frontend/src/utils/severity.ts`

- Firing: arrival + deadcode (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- deadcode: un-export the items marked as internally used; delete the rest after verifying no dynamic consumers
- dead surface: getSeverityFromLabels, getSeverityColor, getSeverityLabel
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__utils__severity.ts.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/utils/severity.ts" --reason "..."`

### 4. `frontend/src/views/VibecheckView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__VibecheckView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/VibecheckView.tsx" --reason "..."`

### 5. `frontend/src/views/TemporalPipelineView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__TemporalPipelineView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/TemporalPipelineView.tsx" --reason "..."`

### 6. `frontend/e2e/prod/oss-recon.spec.ts`

- Firing: size + smells (4 lanes applicable)
- size: split along responsibility boundaries; add a test before moving logic
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__e2e__prod__oss-recon.spec.ts.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "size:frontend/e2e/prod/oss-recon.spec.ts" --reason "..."`

### 7. `frontend/src/components/vibecheck/Stage4Review.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__vibecheck__Stage4Review.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/vibecheck/Stage4Review.tsx" --reason "..."`

### 8. `frontend/src/components/oss/ForkAssignPanel.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__oss__ForkAssignPanel.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/oss/ForkAssignPanel.tsx" --reason "..."`

### 9. `frontend/src/components/vibecheck/Stage3Assign.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__vibecheck__Stage3Assign.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/vibecheck/Stage3Assign.tsx" --reason "..."`

### 10. `frontend/src/views/HealthCheckView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__HealthCheckView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/HealthCheckView.tsx" --reason "..."`

### 11. `frontend/src/views/TaskAutoView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__TaskAutoView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/TaskAutoView.tsx" --reason "..."`

### 12. `frontend/src/components/oss/ProductionReviewPanel.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__oss__ProductionReviewPanel.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/oss/ProductionReviewPanel.tsx" --reason "..."`

### 13. `frontend/src/store/temporalStore.ts`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__store__temporalStore.ts.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/store/temporalStore.ts" --reason "..."`

### 14. `frontend/src/App.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__App.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/App.tsx" --reason "..."`

### 15. `frontend/src/views/RetroView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__RetroView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/RetroView.tsx" --reason "..."`

### 16. `frontend/src/components/temporal/IssueDetail.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__temporal__IssueDetail.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/temporal/IssueDetail.tsx" --reason "..."`

### 17. `frontend/src/components/temporal/BatchBrowser.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__temporal__BatchBrowser.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/temporal/BatchBrowser.tsx" --reason "..."`

### 18. `frontend/src/components/vibecheck/Stage1Install.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__components__vibecheck__Stage1Install.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/components/vibecheck/Stage1Install.tsx" --reason "..."`

## Single-lane findings (one signal each — weigh accordingly)

Each has a full evidence package in `.vibecompact/findings/`.

- `backend/tests/temporal/test_activities.py` — size: 2217 code lines (tier 3) → `.vibecompact/findings/backend__tests__temporal__test_activities.py.md`
- `frontend/src/components/oss/RepoFilterPopover.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__RepoFilterPopover.tsx.md`
- `frontend/src/views/OSSView.tsx` — arrival → `.vibecompact/findings/frontend__src__views__OSSView.tsx.md`
- `frontend/src/store/taskautoStore.ts` — arrival → `.vibecompact/findings/frontend__src__store__taskautoStore.ts.md`
- `frontend/src/components/common/Navigation.tsx` — arrival → `.vibecompact/findings/frontend__src__components__common__Navigation.tsx.md`
- `frontend/src/components/common/ProgressLog.tsx` — arrival → `.vibecompact/findings/frontend__src__components__common__ProgressLog.tsx.md`
- `frontend/src/components/vibecheck/Stage2Run.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage2Run.tsx.md`
- `frontend/src/api/types.ts` — arrival → `.vibecompact/findings/frontend__src__api__types.ts.md`
- `frontend/src/components/common/FilterBar.tsx` — arrival → `.vibecompact/findings/frontend__src__components__common__FilterBar.tsx.md`
- `frontend/src/utils/diffRenderer.ts` — arrival → `.vibecompact/findings/frontend__src__utils__diffRenderer.ts.md`
- `frontend/src/utils/severity.ts` — arrival → `.vibecompact/findings/frontend__src__utils__severity.ts.md`
- `backend/temporal/activities/submission.py` — size: 857 code lines (tier 2) → `.vibecompact/findings/backend__temporal__activities__submission.py.md`
- `frontend/src/components/oss/PipelineRunsPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__PipelineRunsPanel.tsx.md`
- `frontend/src/components/temporal/EvidencePreview.tsx` — arrival → `.vibecompact/findings/frontend__src__components__temporal__EvidencePreview.tsx.md`
- `frontend/src/api/client.ts` — arrival → `.vibecompact/findings/frontend__src__api__client.ts.md`
- `frontend/src/hooks/index.ts` — arrival → `.vibecompact/findings/frontend__src__hooks__index.ts.md`
- `backend/tests/temporal/test_workflows.py` — size: 778 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_workflows.py.md`
- `backend/tests/temporal/test_gates.py` — size: 747 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_gates.py.md`
- `frontend/src/components/temporal/PipelineInbox.tsx` — arrival → `.vibecompact/findings/frontend__src__components__temporal__PipelineInbox.tsx.md`
- `frontend/src/styles/retro.css` — size: 768 code lines (tier 1) → `.vibecompact/findings/frontend__src__styles__retro.css.md`
- `frontend/e2e/local/harness.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__harness.spec.ts.md`
- `frontend/e2e/local/health.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__health.spec.ts.md`
- `frontend/e2e/local/navigation.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__navigation.spec.ts.md`
- `frontend/e2e/local/pipelines.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__pipelines.spec.ts.md`
- `frontend/e2e/local/retro.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__retro.spec.ts.md`
- `frontend/e2e/local/taskauto.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__taskauto.spec.ts.md`
- `frontend/e2e/local/temporal.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__temporal.spec.ts.md`
- `backend/temporal/workflows/issue_workflow.py` — size: 575 code lines (tier 1) → `.vibecompact/findings/backend__temporal__workflows__issue_workflow.py.md`
- `backend/tests/temporal/test_temporal_routes.py` — size: 558 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_temporal_routes.py.md`
- `scripts/render_actionability_html.py` — size: 551 code lines (tier 1) → `.vibecompact/findings/scripts__render_actionability_html.py.md`
- `backend/helpers/report_generator.py` — size: 550 code lines (tier 1) → `.vibecompact/findings/backend__helpers__report_generator.py.md`
- `scripts/copilot-sessions.py` — size: 517 code lines (tier 1) → `.vibecompact/findings/scripts__copilot-sessions.py.md`
- `backend/tests/taskauto/test_jobs.py` — size: 508 code lines (tier 1) → `.vibecompact/findings/backend__tests__taskauto__test_jobs.py.md`
- `backend/services/oss_fork.py` — size: 500 code lines (tier 1) → `.vibecompact/findings/backend__services__oss_fork.py.md`
- `scripts/retro_report.py` — size: 492 code lines (tier 1) → `.vibecompact/findings/scripts__retro_report.py.md`
- `backend/routes/temporal_routes.py` — size: 490 code lines (tier 1) → `.vibecompact/findings/backend__routes__temporal_routes.py.md`
- `backend/tests/test_task_board.py` — size: 488 code lines (tier 1) → `.vibecompact/findings/backend__tests__test_task_board.py.md`
- `backend/config.py` — deadcode: unconsumed exports: unused variable 'VIBECHECK_WORKFLOW_NAME' → `.vibecompact/findings/backend__config.py.md`
- `backend/routes/action_routes.py` — deadcode: unconsumed exports: unused function 'api_assign_copilot', unused function 'api_approve_pr', unused function 'api_mark_pr_ready' +2 → `.vibecompact/findings/backend__routes__action_routes.py.md`
- `backend/routes/automation_routes.py` — deadcode: unconsumed exports: unused attribute 'public', unused attribute 'max_age', unused function 'automation_openapi' → `.vibecompact/findings/backend__routes__automation_routes.py.md`
- `backend/routes/debug/assignment_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_assign_copilot', unused function 'api_oss_debug_score_issue' → `.vibecompact/findings/backend__routes__debug__assignment_routes.py.md`
- `backend/routes/debug/context_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_build_context', unused function 'api_oss_debug_create_context_issue' → `.vibecompact/findings/backend__routes__debug__context_routes.py.md`
- `backend/routes/debug/fork_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_fork_exists', unused function 'api_oss_debug_fork_repo', unused function 'api_oss_debug_fork_ready' +1 → `.vibecompact/findings/backend__routes__debug__fork_routes.py.md`
- `backend/routes/debug/health_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_gh_health', unused function 'api_oss_debug_aggregator_health', unused function 'api_oss_debug_state_dump' → `.vibecompact/findings/backend__routes__debug__health_routes.py.md`
- `backend/routes/debug/tracking_routes.py` — deadcode: unconsumed exports: unused function 'api_oss_debug_fork_pr_status', unused function 'api_oss_debug_poll_submitted_pr', unused function 'api_oss_debug_notification_preview' → `.vibecompact/findings/backend__routes__debug__tracking_routes.py.md`
- `backend/routes/health_routes.py` — deadcode: unconsumed exports: unused function 'api_healthcheck', unused function 'api_owner' → `.vibecompact/findings/backend__routes__health_routes.py.md`
- `backend/routes/workflow_routes.py` — deadcode: unconsumed exports: unused function 'api_install_vibecheck', unused function 'api_vibecheck_template', unused function 'api_update_vibecheck' +2 → `.vibecompact/findings/backend__routes__workflow_routes.py.md`
- `backend/routes/oss_routes_stage5.py` — deadcode: unconsumed exports: unused function 'api_oss_stage5_submit', unused function 'api_oss_admin_archive_ready_to_submit', unused function 'api_oss_submit_to_origin' +2 → `.vibecompact/findings/backend__routes__oss_routes_stage5.py.md`
- `frontend/src/hooks/useAsyncAction.ts` — smells → `.vibecompact/findings/frontend__src__hooks__useAsyncAction.ts.md`

_Cap: 53 more single-lane firings not packaged this run (per-lane cap 15: arrival +42, size +11). They still fire in the machine data._

## Machine data

Full lane entries, clone partners, scores, and ledger state: `.vibecompact/audit.json` on the data branch, `.vibecompact/out/audit.json` in a local run.
