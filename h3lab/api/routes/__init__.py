"""Route modules, grouped by what the caller is trying to do."""

from __future__ import annotations

from fastapi import APIRouter

from h3lab.api.routes import analysis, arena, events, judge, lab, library, media, runs, studio

ROUTERS: tuple[APIRouter, ...] = (
    lab.router,
    runs.router,
    judge.router,
    arena.router,
    analysis.router,
    library.router,
    media.router,
    events.router,
    studio.router,
)

__all__ = ["ROUTERS"]
