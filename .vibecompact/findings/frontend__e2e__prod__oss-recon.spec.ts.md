# frontend/e2e/prod/oss-recon.spec.ts

Corroborated finding, rank 1 · firing: size + smells · 4 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 1011 code lines (tier 2)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `waitForPanelState` | async function | 1293 | 72–1364 |
| `navigateToOSSTab` | async function | 44 | 28–71 |

`waitForPanelState` alone is 95% of the file — moving it to its own module would relocate the problem, not reduce it. Cut inside it instead:

Suggested first cut: split `waitForPanelState` at its internal boundaries (blocks, route groups, phases) rather than extracting it whole, with a test first.

### smells — 1117 any-typed identifiers (run `npx type-coverage --detail` for positions)

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:frontend/e2e/prod/oss-recon.spec.ts" --reason "..."
vibecheck wontfix|noise|justify "smells:frontend/e2e/prod/oss-recon.spec.ts" --reason "..."
```
