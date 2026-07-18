"""Vercel / local entrypoint — must live at repo root (not under app/)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable in serverless runtimes
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.web import app  # noqa: E402

__all__ = ["app"]
