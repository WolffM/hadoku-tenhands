"""Pm2 entrypoint for the crimson-kitty Temporal worker.

Thin shim: pm2 invokes this directly with `python backend/run_worker.py`
from the tenhands repo root. Python's sys.path[0] is resolved to
this script's directory (`backend/`), so `from temporal.worker import
main` finds the in-repo `backend/temporal/` package rather than the
installed `temporalio` SDK (different top-level names, no conflict).

Kept as a shim (rather than `python -m temporal.worker`) because pm2's
`script` field does not accept `-m` module invocation — it expects a
file path.
"""

from __future__ import annotations

import sys

from temporal.worker import main

if __name__ == "__main__":
    sys.exit(main())
