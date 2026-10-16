"""Backend app package initializer."""

from backend.app import main  # noqa: F401
from backend.app.main import app

__all__ = ["app"]
