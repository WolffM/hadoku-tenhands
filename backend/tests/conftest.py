"""Pytest configuration — add backend/ to sys.path so tests can import modules."""

import sys
import os

# Add the backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
