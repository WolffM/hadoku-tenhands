Run a full batch retrospective report for the given batch name.

Usage examples:
- `/retro-batch jade-hare`
- `/retro-batch jade-hare --full`
- `/retro-batch crimson-kitty`

If no batch name is given, run without `--batch` to get usage help.

Run the following command, substituting the user's argument for the `--batch` flag:

```bash
python3 scripts/retro_report.py --batch $BATCH_NAME $EXTRA_FLAGS
```

Where `$BATCH_NAME` is the first argument the user passed (e.g. `jade-hare`) and `$EXTRA_FLAGS` is anything else (e.g. `--full`).

The report includes:
- Funnel summary (Dispatched → Fork PRs → Upstream PRs → Merged/Open/Closed)
- Human feedback digest (all bot-filtered comments grouped by repo)
- SA patterns (top static analysis findings by frequency)
- Per-issue summary table (stage reached, PR number, comment count, context tier)

Display the output as-is (it is already formatted for terminal). If the command fails because the backend is not running, say so directly and suggest starting it with `cd backend && python3 app.py`.
