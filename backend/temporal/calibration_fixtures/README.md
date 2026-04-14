# Judge calibration fixtures

Hand-scored examples used by `scripts/temporal_judge_calibration.py` to
verify the rubrics in `backend/temporal/rubrics/` still match operator
intent. Phase 1E.5 wants 20 fixtures total: 10 for `relevance_v1` and 10
for `submission_v1`, covering pass / borderline / fail.

## File schema

Each fixture is a JSON file:

```json
{
  "rubric": "relevance_v1",
  "input": "## Issue summary\n\n...the payload the rubric scores...",
  "operator_verdict": "pass",
  "operator_score": 0.9,
  "notes": "why the operator scored it this way — for posterity"
}
```

`rubric` must be one of `relevance_v1` or `submission_v1`. `input` is
exactly what the calibration script will pass to `judge.score()`.
`operator_verdict` ∈ `pass | fail | defer`. `operator_score` is in
`[0.0, 1.0]`.

## How agreement is scored

A fixture passes if BOTH:
1. `abs(judge_score - operator_score) <= 0.15`
2. `judge_verdict == operator_verdict`

A rubric passes calibration if ≥ 80% of its fixtures pass.

## Adding fixtures

The plan calls for 20 hand-scored examples — 10 per rubric. Distribution
target per rubric:
- 4 clear-pass examples (score ≥ 0.85)
- 3 borderline / defer examples (0.55–0.75)
- 3 clear-fail examples (≤ 0.40)

Operator owns this — the calibration is meaningless if the judge agrees
with itself. Hand-score each fixture before running the script.

## Running

```sh
# After adding fixtures, run the script. Requires CLAUDE_CODE_OAUTH_TOKEN.
python3 scripts/temporal_judge_calibration.py

# Or dry-run to verify the fixtures load cleanly:
python3 scripts/temporal_judge_calibration.py --dry-run

# Save a CSV for historical comparison:
python3 scripts/temporal_judge_calibration.py --csv-out state/calibration-2026-04-14.csv
```

If a rubric falls below 80%, edit the rubric markdown and re-run until
agreement returns. **Do not edit fixtures to make them match the judge** —
the operator's verdict is the source of truth.
