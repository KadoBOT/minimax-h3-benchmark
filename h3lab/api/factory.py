"""Module-level app for `uvicorn --reload`, which needs an import string.

Settings come from the environment here, because a reloading worker is a fresh process and
cannot inherit anything the CLI parsed. `h3lab serve --reload` sets the variables first.
"""

from __future__ import annotations

from h3lab.api.app import create_app
from h3lab.settings import Settings

app = create_app(settings=Settings.from_env())

__all__ = ["app"]
