Run a single-issue retrospective report for the given PR reference.

Usage examples:
- `/retro-pr microsoft/markitdown#183`
- `/retro-pr microsoft/markitdown#183 --full`
- `/retro-pr microsoft/markitdown#183 --batch jade-hare`

The argument format is `owner/repo#N` where N is the **issue number** (not the PR number).

Run the following command, substituting the user's argument for the `--pr` flag:

```bash
python3 /mnt/c/Users/Hadoku/Documents/repos/vibedispatch/scripts/retro_report.py --pr $ARGS
```

Where `$ARGS` is everything the user passed after `/retro-pr`. If the user passed `--full`, include it. If the user passed `--batch BATCH`, include it.

Display the output as-is (it is already formatted for terminal). If the command fails because the backend is not running, say so directly and suggest starting it with `cd backend && python3 app.py`.
