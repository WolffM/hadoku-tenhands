# vibeCompact — agent briefing

Anchor: `89575ab62d18` (2026-08-24). Generated with the audit report; findings below are corroborated by ≥2 independent lanes unless marked otherwise.

## Ground rules

- Fixes need no ceremony: land a commit touching a flagged file and the next audit stamps it `fixed` automatically. Partial progress shows as **improving**.
- Findings you judge wrong get verdicts, not workarounds — the commands are attached to each finding. Verdicts are maintainer decisions; confirm with the human before filing one.
- Do not delete anything without verifying reachability yourself first: string references, dynamic imports, runner and workflow configs.
- Coverage warning: 1 of 6 planned lanes unavailable or degraded (deadcode). Corroboration was weakened this run — an empty corroborated section is a coverage statement, and single-lane findings deserve more weight than usual.

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

### 3. `frontend/src/views/VibecheckView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__VibecheckView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/VibecheckView.tsx" --reason "..."`

### 4. `frontend/src/views/TemporalPipelineView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__TemporalPipelineView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/TemporalPipelineView.tsx" --reason "..."`

### 5. `frontend/src/views/OSSView.tsx`

- Firing: arrival + smells (6 lanes applicable)
- arrival: add at least one test whose import path reaches this file before changing it further
- smells: replace any-typed identifiers with concrete types
- **Evidence package** (exact symbols, ranges, verification): `.vibecompact/findings/frontend__src__views__OSSView.tsx.md`
- If wrong or accepted: `vibecheck wontfix|noise|justify "arrival:frontend/src/views/OSSView.tsx" --reason "..."`

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

- `frontend/src/components/oss/RepoFilterPopover.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__RepoFilterPopover.tsx.md`
- `frontend/src/views/OSSView.tsx` — arrival → `.vibecompact/findings/frontend__src__views__OSSView.tsx.md`
- `frontend/src/components/vibecheck/Stage2Run.tsx` — arrival → `.vibecompact/findings/frontend__src__components__vibecheck__Stage2Run.tsx.md`
- `frontend/src/store/taskautoStore.ts` — arrival → `.vibecompact/findings/frontend__src__store__taskautoStore.ts.md`
- `frontend/src/components/common/Navigation.tsx` — arrival → `.vibecompact/findings/frontend__src__components__common__Navigation.tsx.md`
- `frontend/src/components/common/ProgressLog.tsx` — arrival → `.vibecompact/findings/frontend__src__components__common__ProgressLog.tsx.md`
- `frontend/src/components/common/FilterBar.tsx` — arrival → `.vibecompact/findings/frontend__src__components__common__FilterBar.tsx.md`
- `backend/temporal/activities/submission.py` — size: 857 code lines (tier 2) → `.vibecompact/findings/backend__temporal__activities__submission.py.md`
- `frontend/src/components/oss/PipelineRunsPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__PipelineRunsPanel.tsx.md`
- `frontend/src/components/temporal/EvidencePreview.tsx` — arrival → `.vibecompact/findings/frontend__src__components__temporal__EvidencePreview.tsx.md`
- `frontend/src/api/client.ts` — arrival → `.vibecompact/findings/frontend__src__api__client.ts.md`
- `frontend/src/hooks/index.ts` — arrival → `.vibecompact/findings/frontend__src__hooks__index.ts.md`
- `backend/tests/temporal/test_workflows.py` — size: 778 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_workflows.py.md`
- `backend/tests/temporal/test_gates.py` — size: 747 code lines (tier 1) → `.vibecompact/findings/backend__tests__temporal__test_gates.py.md`
- `frontend/src/components/temporal/PipelineInbox.tsx` — arrival → `.vibecompact/findings/frontend__src__components__temporal__PipelineInbox.tsx.md`
- `frontend/src/components/oss/RepoHealthPanel.tsx` — arrival → `.vibecompact/findings/frontend__src__components__oss__RepoHealthPanel.tsx.md`
- `frontend/src/styles/retro.css` — size: 768 code lines (tier 1) → `.vibecompact/findings/frontend__src__styles__retro.css.md`
- `frontend/e2e/local/harness.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__harness.spec.ts.md`
- `frontend/e2e/local/health.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__health.spec.ts.md`
- `frontend/e2e/local/navigation.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__navigation.spec.ts.md`
- `frontend/e2e/local/pipelines.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__pipelines.spec.ts.md`
- `frontend/e2e/local/retro.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__retro.spec.ts.md`
- `frontend/e2e/local/taskauto.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__taskauto.spec.ts.md`
- `frontend/e2e/local/temporal.spec.ts` — smells → `.vibecompact/findings/frontend__e2e__local__temporal.spec.ts.md`
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
- `backend/services/dispatchers.py` — size: 480 code lines (tier 1) → `.vibecompact/findings/backend__services__dispatchers.py.md`
- `frontend/src/store/pipelineStore.ts` — arrival → `.vibecompact/findings/frontend__src__store__pipelineStore.ts.md`
- `frontend/src/api/endpoints.ts` — arrival → `.vibecompact/findings/frontend__src__api__endpoints.ts.md`
- `frontend/src/hooks/useAsyncAction.ts` — smells → `.vibecompact/findings/frontend__src__hooks__useAsyncAction.ts.md`

_Cap: 55 more single-lane firings not packaged this run (per-lane cap 15: arrival +42, size +13). They still fire in the machine data._

## Machine data

Full lane entries, clone partners, scores, and ledger state: `.vibecompact/audit.json` on the data branch, `.vibecompact/out/audit.json` in a local run.
