"""Live updates over Server-Sent Events.

The queue is worked by a background thread, so the browser must be told what changed rather
than poll for it. Reconnecting clients pass the last sequence number they saw and the replay
buffer fills the gap, so a dropped socket does not leave a stale page.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from h3lab.api.deps import LabDep
from h3lab.engine.events import Event

router = APIRouter(tags=["events"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Without this a reverse proxy may buffer the stream and deliver nothing until it ends.
    "X-Accel-Buffering": "no",
}
POLL_S = 1.0
KEEPALIVE_S = 15.0


@router.get("/events")
async def events(lab: LabDep, request: Request, after: int = 0) -> StreamingResponse:
    subscription = lab.events.subscribe(replay_after=after)

    async def pump() -> object:
        idle = 0.0
        try:
            while not await request.is_disconnected():
                # The bus is thread-blocking by design; keep the event loop free while waiting.
                event = await asyncio.to_thread(subscription.get, POLL_S)
                if event is not None:
                    idle = 0.0
                    yield event.to_sse()
                    continue
                idle += POLL_S
                if idle >= KEEPALIVE_S:
                    idle = 0.0
                    yield f": keep-alive {lab.events.last_seq}\n\n"
        finally:
            subscription.close()

    return StreamingResponse(pump(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/events/recent")
def recent_events(lab: LabDep, after: int = 0) -> list[Event]:
    """The replay buffer as JSON, for a client that cannot hold a stream open."""
    return lab.events.history(after=after)
