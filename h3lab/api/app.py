"""The app: wire settings, the Lab, error translation, routes, and the built UI together.

Routes are thin on purpose — they parse, call the Lab, and return a model. Everything that
needs more than one repository lives in `h3lab.engine.lab`, so the same operation is
reachable from a test or a script without a web server.
"""

from __future__ import annotations

import asyncio
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Iterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from h3lab.api import errors
from h3lab.api.deps import resolve_lab
from h3lab.api.routes import ROUTERS
from h3lab.engine.lab import Lab
from h3lab.settings import Settings

API = "/api"

# The Vite dev server runs on its own port and talks to this API directly. Loopback and LAN
# origins are allowed, and no credentials travel.
LOCAL_ORIGINS = r"http://(127\.0\.0\.1|localhost|\[::1\]|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?"


def create_app(lab: Lab | None = None, settings: Settings | None = None) -> FastAPI:
    resolved = settings or (lab.settings if lab else Settings.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Opening the store and starting the worker both block; keep startup off the loop.
        started = await asyncio.to_thread(resolve_lab, app)
        await asyncio.to_thread(started.reconcile)
        try:
            yield
        finally:
            lab_to_close = getattr(app.state, "lab", None) or started
            if lab_to_close is not None:
                await asyncio.to_thread(lab_to_close.close)
            if getattr(app.state, "owns_lab", False):
                app.state.lab = None

    app = FastAPI(
        title="H3 Lab",
        version="2.0",
        summary="Benchmark, judge, and compare MiniMax H3 video generations.",
        docs_url=f"{API}/docs",
        redoc_url=None,
        openapi_url=f"{API}/openapi.json",
        swagger_ui_oauth2_redirect_url=f"{API}/docs/oauth2-redirect",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.lab = lab
    app.state.owns_lab = lab is None

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOCAL_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )

    errors.install(app, resolved)
    for router in ROUTERS:
        app.include_router(router, prefix=API, responses=errors.PROBLEM_RESPONSES)
    _mount_spa(app, resolved)
    return app


def _mount_spa(app: FastAPI, settings: Settings) -> None:
    """Serve the built front end, letting client-side routes fall back to the shell."""

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path == API.lstrip("/") or path.startswith(API.lstrip("/") + "/"):
            # An unknown API path must answer as the API, not hand the browser the HTML
            # shell — a fetch that receives HTML fails on parsing instead of on the 404.
            return errors.problem(404, "not_found", "no such endpoint", f"/{path}")
        index = settings.web_dist / "index.html"
        if not index.is_file():
            return Response(
                _NO_BUILD.format(dist=settings.web_dist),
                media_type="text/html",
                status_code=503,
            )
        root = settings.web_dist.resolve()
        candidate = (root / path).resolve() if path else index
        if candidate.is_file() and (candidate == index.resolve() or root in candidate.parents):
            media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            if candidate.name == "index.html":
                headers = {"Cache-Control": "no-cache"}
            return FileResponse(candidate, media_type=media_type, headers=headers)
        # Anything else is a route the browser resolves itself.
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})


_NO_BUILD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>H3 Lab — not built yet</title>
<style>
  body {{ background:#09090b; color:#e4e4e7; margin:0; min-height:100vh; display:grid;
          place-items:center; font:15px/1.65 ui-sans-serif,system-ui,sans-serif }}
  main {{ max-width:42rem; padding:2.5rem }}
  h1 {{ font-size:1.4rem; margin:0 0 .9rem; letter-spacing:-.01em }}
  p {{ color:#a1a1aa; margin:.6rem 0 }}
  code {{ background:#18181b; border:1px solid #27272a; border-radius:.3rem;
          padding:.15rem .4rem; color:#a5d8ff; font-size:.9em }}
  a {{ color:#a5d8ff }}
</style></head>
<body><main>
  <h1>The interface has not been built yet</h1>
  <p>The API is running. To build the front end once:</p>
  <p><code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code></p>
  <p>It is expected at <code>{dist}</code>. While developing, run <code>npm run dev</code>
     and open the Vite server instead — it proxies to this API.</p>
  <p><a href="/api/docs">Browse the API →</a></p>
</main></body></html>"""


def routes_of(app: FastAPI) -> Iterator[tuple[str, str]]:
    """Every (method, path) pair the app answers. Used by `h3lab --check`."""
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        for method in sorted(methods):
            yield method, path


__all__ = ["API", "create_app", "routes_of"]
