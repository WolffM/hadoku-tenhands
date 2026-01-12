# VibeDispatch Milestones

## Philosophy

- Vibecheck is the test case for everything
- Each milestone should result in vibecheck still working
- Flexibility over features - build the toolbox, not the tool
- GitHub Issues until it hurts, then abstract
- **All gates by default, yolo to bypass** - humans stay in control
- **Dynamic complexity** - no static thresholds, each run is a judgment call

---

## M1: Child-App Migration

**Goal**: Transpile VibeDispatch to work as a child-app of the main site

**Why first**:

- Current raw HTML/JS is hard to improve and doesn't feel right
- Better to migrate now than build pipeline features on a foundation you dislike
- Child-app structure provides consistent patterns for future development

**Success criteria**:

- VibeDispatch runs as child-app of main site
- All existing functionality preserved (dashboard, stages, assign, review)
- Development experience is improved (whatever that means for the child-app framework)
- Template structure provided by user, implementation follows that pattern

**Key decisions**:

- Await child-app template from user
- Identify what Flask backend pieces remain vs get absorbed

---

## M2: Pipeline Schema & Vibecheck Representation

**Goal**: Define minimal pipeline YAML schema, represent current vibecheck flow as first pipeline

**Success criteria**:

- vibecheck pipeline defined in `/pipelines/staticanalysis.yml`
- Schema supports stages and agents (minimal viable schema)
- Schema is expandable - we add fields as we discover needs
- No runtime changes yet - this is just the spec

**Key decisions**:

- Pipeline schema format (YAML)
- How stages reference agents (by name, agent = system prompt selection)
- Gates are implicit (all stages gated by default, no schema config needed)
- Context requirements deferred - add to schema when M5 needs it

**Minimal schema example**:

```yaml
name: Static Analysis (VibeCheck)
stages:
  - name: scan
    agent: vibecheck
  - name: assign
    agent: copilot
  - name: implement
    agent: copilot
  - name: review
    agent: human
```

---

## M3: Pipeline View UI

**Goal**: Dashboard shows pipeline-centric view instead of stage-centric

**Success criteria**:

- UI reads pipeline definitions from `/pipelines/*.yml`
- Shows vibecheck pipeline with its stages
- Current items visible at their current stage
- Existing functionality still works (assign copilot, review PRs)
- **"Yolo" button** at each gate - bypasses remaining gates for this item

**Key decisions**:

- How pipeline state is tracked (GitHub labels? local DB? both?)
- Navigation model (pipeline list → pipeline detail → item detail)
- Yolo state is per-item runtime state, not persisted in schema

---

## M4: Pipeline State Machine

**Goal**: Orchestrator understands stage transitions and gates

**Success criteria**:

- Items move through stages based on pipeline definition
- All stages gated by default - block until human approves
- Yolo mode: human can mark item as "auto-advance" to skip remaining gates
- Vibecheck items flow through correctly

**Key decisions**:

- State storage (start with GitHub labels, design for abstraction)
- Event model (what triggers transitions)
- How to handle items that skip stages or go backwards
- Yolo state per item (label? local state? both?)

---

## M5: Agent Abstraction Layer

**Goal**: Decouple "who does the work" from pipeline definition

**Success criteria**:

- Agents defined separately from pipelines (agent = system prompt + config)
- Vibecheck uses: `vibecheck` (CLI), `copilot` (GitHub), `human` (manual)
- Agent interface is generic enough for Claude Code, Cursor, custom scripts
- Pipeline references agents by name, not implementation

**Key decisions**:

- Agent interface contract
- How agents report completion/failure
- How agents receive context
- **Session handoff**: How to preserve context when agent fails/times out (for retry)

---

## M6: Context Bundling Foundation

**Goal**: Pipelines can declare context needs, system bundles it

**Success criteria**:

- Pipeline schema includes context requirements per stage
- Basic context types work: `issue`, `files`, `diff`, `repo_structure`
- Context passed to agents in consistent format
- Vibecheck stages get appropriate context

**Key decisions**:

- Context type taxonomy
- Bundling format (XML tags? JSON? Markdown sections?)
- How much context is "enough" (token budgets?)

---

## M7: Persistence Abstraction

**Goal**: Decouple from GitHub Issues, enable future alternatives

**Success criteria**:

- Storage interface defined (issues, state, context cache)
- GitHub adapter implements interface
- All existing code uses interface, not GitHub directly
- Could swap to Chainlink-style local storage later

**Key decisions**:

- Interface surface area (CRUD + query patterns)
- Migration path for existing data
- Sync strategy if hybrid (local + GitHub)

---

## M8: Investigate Failures Pipeline

**Goal**: Prove the system works for a planning-heavy pipeline type

**Why this pipeline**:

- Requires planning (can't just assign to Copilot without diagnosis)
- Exercises full Objective → Plan → Tasks → Implementation → Review flow
- Immediately useful (real failing actions to investigate)

**Pipeline structure**:

```yaml
name: Investigate Failures
stages:
  - name: detect
    agent: gh-cli # Fetch failed workflow runs
  - name: investigate
    agent: claude # Read logs, identify root cause
  - name: plan
    agent: claude # Propose fix approach
  - name: tasks
    agent: claude # Break plan into atomic tasks
  - name: implement
    agent: copilot # Execute tasks
  - name: review
    agent: human
```

**Success criteria**:

- Pipeline fetches real GitHub Actions failures
- Planning agent produces actionable diagnosis
- Tasks generated from plan are specific and scoped
- Both pipelines (vibecheck + investigate) work simultaneously

**Key validation**:

- Does the planning stage add value over direct assignment?
- Is the task breakdown useful or overhead?
- What context does the planning agent need?

---

## Future Milestones (Not Yet Scoped)

### M9: Advanced Context Selection

- Repo map generation
- Embedding-based file relevance
- Island detection for monorepos

### M10: Multi-Repo Support

- Linked pipelines across repos
- Shared context/schemas

### M11: Retrospective Pipeline

- Analyze merged PRs for patterns
- Generate improvement objectives

### M12: Additional Pipeline Types

- Formatting/linting (lightweight, likely auto-yolo)
- Dependency updates
- Documentation generation

---

## Cross-Cutting Concerns (Every Milestone)

- **Vibecheck keeps working** - regression test after each milestone
- **Schema backward compatibility** - old pipeline defs don't break
- **Escape hatches** - manual overrides always available
- **Observability** - can see what's happening and why

---

## Risk Flags

| Risk               | Mitigation                                                                       |
| ------------------ | -------------------------------------------------------------------------------- |
| GitHub rate limits | M7 abstracts storage early                                                       |
| Schema churn       | Start minimal, expand as needed (don't over-specify upfront)                     |
| Over-engineering   | Each milestone must ship working vibecheck                                       |
| Context complexity | M6 starts simple, defer smart selection to M9                                    |
| Too many gates     | Yolo mode provides escape hatch; adjust default behavior based on usage patterns |
| Planning overhead  | M8 validates whether planning adds value; may simplify if overhead > benefit     |
