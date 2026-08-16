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
from h3lab.shared.client import SharedServiceClient

_LOCK = threading.RLock()


def resolve_lab(app: Starlette) -> Lab:
    """Return the app's Lab, opening one on first use.

    Construction is deferred so that building the app (for the OpenAPI schema, say) does not
    open a database or start a worker thread.
    """
    with _LOCK:
        existing = getattr(app.state, "lab", None)
        if existing is None:
            existing = Lab(
                app.state.settings,
                shared_client=resolve_shared_client(app),
            )
            app.state.lab = existing
            app.state.owns_lab = True
        return existing


def get_lab(request: Request) -> Lab:
    return resolve_lab(request.app)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def resolve_shared_client(app: Starlette) -> SharedServiceClient:
    with _LOCK:
        existing = getattr(app.state, "shared_client", None)
        if existing is None:
            existing = SharedServiceClient(app.state.settings.shared_service_url)
            app.state.shared_client = existing
            app.state.owns_shared_client = True
        return existing


def get_shared_client(request: Request) -> SharedServiceClient:
    return resolve_shared_client(request.app)


LabDep = Annotated[Lab, Depends(get_lab)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SharedClientDep = Annotated[SharedServiceClient, Depends(get_shared_client)]

__all__ = [
    "LabDep",
    "SettingsDep",
    "SharedClientDep",
    "get_lab",
    "get_settings",
    "get_shared_client",
    "resolve_lab",
    "resolve_shared_client",
]
