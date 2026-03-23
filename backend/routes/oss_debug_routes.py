"""
OSS debug routes — thin shim.

All debug route implementations have been moved to routes/debug/.
This module exists solely so that ``from . import oss_debug_routes`` in
routes/__init__.py continues to work without any changes.
"""

from . import debug  # noqa: F401  — triggers registration of all debug sub-modules
