"""Vercel / local entrypoint — exports the FastAPI `app` instance."""

from app.main import app

__all__ = ["app"]
