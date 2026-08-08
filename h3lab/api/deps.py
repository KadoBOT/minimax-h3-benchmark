"""Shared route dependencies.

The Lab lives on ``app.state`` rather than in a module global, so two apps can run in one
process (which is what the test suite does) without sharing a database or a worker thread.
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import Depends, Request
from starlette.applications import Starlette

from h3lab.engine.lab import Lab
from h3lab.settings import Settings

_LOCK = threading.Lock()


def resolve_lab(app: Starlette) -> Lab:
    """Return the app's Lab, opening one on first use.

    Construction is deferred so that building the app (for the OpenAPI schema, say) does not
    open a database or start a worker thread.
    """
    with _LOCK:
        existing = getattr(app.state, "lab", None)
        if existing is None:
            existing = Lab(app.state.settings)
            app.state.lab = existing
            app.state.owns_lab = True
        return existing


def get_lab(request: Request) -> Lab:
    return resolve_lab(request.app)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


LabDep = Annotated[Lab, Depends(get_lab)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

__all__ = ["LabDep", "SettingsDep", "get_lab", "get_settings", "resolve_lab"]
