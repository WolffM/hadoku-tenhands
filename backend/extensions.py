"""
Shared Flask extensions — initialized here, attached to app in app.py.

Avoids circular imports between app.py and route modules.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)
