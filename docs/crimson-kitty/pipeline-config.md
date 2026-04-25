# Pipeline configuration

How crimson-kitty plugs into the existing UI alongside `vibecheck` and
`oss-contribution`.

## The current pipeline picker

`frontend/src/views/PipelineSelectView.tsx` shows tiles for each available
pipeline. Today there are two:
- **vibecheck** — the install-and-run-tests flow
- **oss-contribution** — the current dispatch-and-watch pipeline

Each pipeline has:
- A view (`VibecheckView.tsx`, `OSSView.tsx`)
- A store slice (`vibeCheckStore.ts`, `ossStore.ts`)
- A set of components (`components/vibecheck/`, `components/oss/`)
- A backend route group (`/dispatch/api/oss/...`)

## crimson-kitty as a third tile

We add a third tile: **crimson-kitty (Temporal pipeline)**.

```
┌─────────────────────────────────────────────────────────────┐
│  PipelineSelectView                                         │
│                                                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │  vibecheck   │  │ oss-contribution │  │ crimson-kitty│ │
│  │              │  │   (legacy)       │  │   (Temporal) │ │
│  │  install &   │  │                  │  │              │ │
│  │  validate    │  │  legacy linear   │  │  state-machine│ │
│  │              │  │  stage runner    │  │  with gates  │ │
│  └──────────────┘  └──────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Naming

- **Internal slug**: `temporal` (matches `vibecheck`, `oss`)
- **Display name**: "crimson-kitty"
- **Subtitle**: "State-machine pipeline with quality gates"
- **Badge**: "v3" or "new" — never removed; old pipelines stay as archival (decision Q6)

The batch name (`crimson-kitty`) is *also* the first batch we'll dispatch
through this pipeline. After the v1 release we'll continue using
adjective-animal batch names per dispatch run, but the pipeline itself stays
called "temporal" internally.

## Routing

| URL | View | Component |
|---|---|---|
| `/` | `PipelineSelectView` | tile picker |
| `/vibecheck` | `VibecheckView` | (existing) |
| `/oss` | `OSSView` | (existing) |
| `/temporal` | `TemporalPipelineView` | (new) |
| `/temporal/inbox` | `PipelineInbox` | (new) |
| `/temporal/issue/:slug/:number` | `IssueDetail` | (new) |
| `/retro` | `RetroView` | (existing, **gets a tab strip** for Legacy / Temporal — two separate retro tools, no shared code per Q7) |

## Backend routes

| URL | Module | Purpose |
|---|---|---|
| `/dispatch/api/temporal/batches` | `routes/temporal_routes.py` | List crimson-kitty batches |
| `/dispatch/api/temporal/batch/:id` | `routes/temporal_routes.py` | Batch detail |
| `/dispatch/api/temporal/inbox` | `routes/temporal_routes.py` | Operator inbox: issues awaiting human gates |
| `/dispatch/api/temporal/issue/:slug/:number` | `routes/temporal_routes.py` | Issue detail with timeline + evidence |
| `/dispatch/api/temporal/issue/:slug/:number/signal` | `routes/temporal_routes.py` | POST a Temporal signal: approve/abort/retry. Drives both judge-defer recovery and the `awaiting_signoff` operator-go/no-go (see [state-machine.md#awaiting_signoff](state-machine.md)). |
| `/dispatch/api/temporal/dispatch` | `routes/temporal_routes.py` | Start a new batch |
| `/dispatch/api/temporal/health` | `routes/temporal_routes.py` | Temporal cluster + worker health |
| `/dispatch/api/temporal/evidence/:batch_id/:issue_id` | `routes/temporal_routes.py` | List evidence stages and files for an issue |
| `/dispatch/api/temporal/evidence/:batch_id/:issue_id/:filepath` | `routes/temporal_routes.py` | Raw file content from the evidence store |
| `/dispatch/api/temporal/judge/canary` | `routes/temporal_routes.py` | POST — invoke the judge canary and return `{reachable, claude_bin, oauth_token_set}`. Diagnostic for verifying the claude CLI is wired up without running a full workflow |

The existing `/dispatch/api/oss/*` routes stay untouched.

## Store slice

```typescript
// frontend/src/store/temporalStore.ts
interface TemporalStore {
  batches: TemporalBatch[]
  currentBatch: TemporalBatch | null
  inbox: InboxEntry[]
  issueDetail: Record<string, IssueState>

  // Actions
  fetchBatches: () => Promise<void>
  fetchBatch: (id: string) => Promise<void>
  fetchInbox: () => Promise<void>
  fetchIssue: (slug: string, number: number) => Promise<void>
  signalIssue: (slug: string, number: number, decision: HumanDecision) => Promise<void>
  dispatchBatch: (issues: IssueRef[]) => Promise<void>
}
```

## Operator inbox UX

The inbox is the load-bearing feature for the operator. It needs to make
"approve/abort" decisions fast.

```
┌──────────────────────────────────────────────────────────────────┐
│ Pipeline Inbox  ·  3 awaiting decision                           │
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ ⚠  microsoft/markitdown#183                                  │ │
│ │    State: reproduced  →  fixed                               │ │
│ │    Gate: relevance (judge, score=0.52)                       │ │
│ │    Reason: "Diff includes unrelated import cleanup in        │ │
│ │             3 files outside the stated issue scope."         │ │
│ │    Evidence: [diff.patch] [files_touched.txt] [issue brief]  │ │
│ │                                                              │ │
│ │    [Approve & continue]  [Abort issue]  [Retry stage]        │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ ⚠  puppeteer/puppeteer#5096                                  │ │
│ │    State: verified  →  reviewed                              │ │
│ │    Gate: verified_evidence_present (mechanical)              │ │
│ │    Reason: "before/after screenshots visually identical      │ │
│ │             (diff=0.012)."                                   │ │
│ │    Evidence: [before.png] [after.png] [test_output.txt]      │ │
│ │                                                              │ │
│ │    [Approve & continue]  [Abort issue]  [Retry stage]        │ │
│ └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

Decisions made in the inbox send Temporal signals to the workflows,
unblocking them. The workflow continues from where it paused.

The inbox surfaces two distinct entry kinds via the same UI:

- **Judge defer** (gate name = `relevance` or `submission_judge`,
  score populated). The operator is reviewing borderline machine
  output and casting the deciding vote.
- **Operator signoff** (gate name = `operator_signoff`, score=null).
  Submittable gates have all passed; the fork preview PR is ready
  for the operator's last look. Approve = pipeline reads the LIVE
  fork PR title + body and opens the upstream PR with whatever the
  operator left there (including any manual edits the operator
  made on GitHub — screenshots, expanded prose, repro fixes).
  Abort = workflow terminates without shipping.

Both use the same `submit_human_decision` Temporal signal, so the
existing UI buttons are reused. The card distinguishes the two via
the `gate_name`. The operator-signoff card should link out to the
fork preview PR URL prominently — that's the editing surface, not
the evidence file browser. Evidence files stay available for audit
but aren't where edits land.

## Evidence file browser

Each issue card on the retro view exposes a stage-by-stage file tree
sourced from the evidence store. The UI calls
`GET /api/temporal/evidence/:batch_id/:issue_id` to list stages + file
names, and `GET /api/temporal/evidence/:batch_id/:issue_id/:filepath`
to fetch raw file content (diffs, JSON, markdown, images). Rendered
inline via the existing `components/temporal/EvidencePreview.tsx`.

This is the operator's primary tool for auditing why a gate passed or
failed — the full evidence trail is browsable without shelling into the
host.

## Discord notifications wired through Temporal

The existing `helpers/notifications.py` Discord functions become activities
called from workflow side-effect points:

| Activity | Triggered when | Notification |
|---|---|---|
| `notify_dispatched_activity` | `eligible → forked` | "Dispatched to {repo}" |
| `notify_inbox_queue_activity` | gate Defer | "{N} issues awaiting review" (rate-limited to once per hour) |
| `notify_human_comments_activity` | watcher poll detects new human comment | per-comment Discord alert (existing behavior) |
| `notify_upstream_submitted_activity` | `submittable → submitted` | "Submitted upstream PR #{N}" |
| `notify_upstream_merged_activity` | `submitted → merged` | "Merged 🎉" |
| `notify_upstream_closed_activity` | `submitted → closed_by_upstream` | "Closed by {closer}" |
| `notify_aborted_activity` | any → `aborted` | "Aborted: {reason}" (rate-limited per batch) |

Existing Discord webhook env vars (`DISCORD_WEBHOOK_URL`,
`DISCORD_TEST_WEBHOOK_URL`) are unchanged. Test mode still routes to the
test channel via the autouse fixture.
