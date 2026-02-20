"""
VibeDispatch - API Backend for GitHub Repository Management

This Flask app serves as the API backend for the VibeDispatch React frontend.
All page rendering has been moved to the React microfrontend.
"""

import os

from flask import Flask, request, jsonify

# Import the blueprint with all routes registered
try:
    from .routes import bp
except ImportError:
    from routes import bp

# URL prefix for deployment behind edge-router at hadoku.me/dispatch/*
# Set URL_PREFIX="" for local development without prefix
URL_PREFIX = os.environ.get("URL_PREFIX", "/dispatch")

app = Flask(__name__)


# ============ CORS Support ============
@app.after_request
def add_cors_headers(response):
    """Add CORS headers for development with React frontend."""
    # In production, the React app is served from the same origin
    # In development, React runs on localhost:5173
    origin = request.headers.get('Origin', '')
    if origin in ['http://localhost:5175', 'http://127.0.0.1:5175', 'http://localhost:5173', 'http://localhost:5174']:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-User-Key'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


@app.route('/')
def api_root():
    """API info endpoint."""
    return jsonify({"message": "VibeDispatch API", "docs": "/api/"})


# Register blueprint with URL prefix
app.register_blueprint(bp, url_prefix=URL_PREFIX)


if __name__ == "__main__":
    # Use environment variable to control debug mode (defaults to False for security)
    # Set FLASK_ENV=development to enable debug mode in local development
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    app.run(debug=debug_mode, port=5000)
