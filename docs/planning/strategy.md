# VibeDispatch Milestones

## Philosophy
- Vibecheck is the test case for everything
- Each milestone should result in vibecheck still working
- Flexibility over features - build the toolbox, not the tool
- GitHub Issues until it hurts, then abstract

---

## M1: Pipeline Schema & Vibecheck Representation
**Goal**: Define pipeline YAML schema, represent current vibecheck flow as first pipeline

**Success criteria**:
- vibecheck pipeline defined in `/pipelines/staticanalysis.yml`
- Schema supports stages, agents, review gates, context requirements
- Schema is flexible enough that we can imagine other pipelines fitting
- No runtime changes yet - this is just the spec

**Key decisions**:
- Pipeline schema format
- How stages reference agents/tools
- How context requirements are declared
- How review gates are configured

---

## M2: Pipeline View UI
**Goal**: Dashboard shows pipeline-centric view instead of stage-centric

**Success criteria**:
- UI reads pipeline definitions from `/pipelines/*.yml`
- Shows vibecheck pipeline with its stages
- Current items visible at their current stage
- Existing functionality still works (assign copilot, review PRs)

**Key decisions**:
- How pipeline state is tracked (GitHub labels? local DB? both?)
- Navigation model (pipeline list → pipeline detail → item detail)

---

## M3: Pipeline State Machine
**Goal**: Orchestrator understands stage transitions and gates

**Success criteria**:
- Items move through stages based on pipeline definition
- Review gates block until human approves
- Auto-advance works for stages without gates
- Vibecheck items flow through correctly

**Key decisions**:
- State storage (start with GitHub labels, design for abstraction)
- Event model (what triggers transitions)
- How to handle items that skip stages or go backwards

---

## M4: Agent Abstraction Layer
**Goal**: Decouple "who does the work" from pipeline definition

**Success criteria**:
- Agents defined separately from pipelines
- Vibecheck uses: `scanner` (vibecheck CLI), `implementer` (Copilot), `reviewer` (human)
- Agent interface is generic enough for Claude Code, Cursor, custom scripts
- Pipeline references agents by name, not implementation

**Key decisions**:
- Agent interface contract
- How agents report completion/failure
- How agents receive context

---

## M5: Context Bundling Foundation
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

## M6: Persistence Abstraction
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

## M7: Second Pipeline (Validation)
**Goal**: Prove the system works for a different pipeline type

**Success criteria**:
- New pipeline added (suggestion: `formatting` or `dependency-update`)
- Uses different stages/gates than vibecheck
- Possibly different agents
- Both pipelines work simultaneously

**Key decisions**:
- Which pipeline type to add
- What new capabilities it requires (if any)

---

## Future Milestones (Not Yet Scoped)

### M8: Planning Agent Integration
- Claude Code or similar for objective→plan→tasks decomposition
- Human review of generated plans

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

---

## Cross-Cutting Concerns (Every Milestone)

- **Vibecheck keeps working** - regression test after each milestone
- **Schema backward compatibility** - old pipeline defs don't break
- **Escape hatches** - manual overrides always available
- **Observability** - can see what's happening and why

---

## Risk Flags

| Risk | Mitigation |
|------|------------|
| GitHub rate limits | M6 abstracts storage early |
| Schema churn | Validate schema against 3+ imagined pipelines before implementing |
| Over-engineering | Each milestone must ship working vibecheck |
| Context complexity | M5 starts simple, defer smart selection to M9 |