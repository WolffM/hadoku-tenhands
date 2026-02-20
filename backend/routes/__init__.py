"""
Routes package - defines the shared Blueprint for all API routes.
"""

from flask import Blueprint

bp = Blueprint('dispatch', __name__)

# Import route modules AFTER bp is created to register their @bp.route decorators
from . import health_routes    # noqa: E402, F401
from . import action_routes    # noqa: E402, F401
from . import workflow_routes  # noqa: E402, F401
from . import pipeline_routes  # noqa: E402, F401
