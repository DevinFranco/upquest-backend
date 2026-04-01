"""
UpQuest – Vercel serverless entrypoint.
Vercel looks for an ASGI app exported from api/index.py.
"""
import sys
import os

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app  # noqa: F401 – Vercel picks up 'app' automatically
