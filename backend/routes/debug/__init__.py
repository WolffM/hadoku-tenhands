"""
Debug routes package — groups diagnostic endpoints by concern.

All modules register routes on the shared `bp` from routes/__init__.py.
"""

from . import health_routes      # noqa: F401  — /debug/gh-health, aggregator-health, state-dump
from . import fork_routes        # noqa: F401  — /debug/fork-exists, fork-repo, fork-ready, sync-fork
from . import context_routes     # noqa: F401  — /debug/build-context, create-context-issue
from . import assignment_routes  # noqa: F401  — /debug/assign-copilot, score-issue
from . import tracking_routes    # noqa: F401  — /debug/fork-pr-status, poll-submitted-pr, notification-preview
