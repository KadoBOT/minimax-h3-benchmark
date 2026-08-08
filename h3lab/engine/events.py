"""In-process event bus with a replay buffer, feeding the browser over SSE.

Every subscriber gets its own bounded queue. A browser tab that stops reading fills its
queue and starts losing the oldest events; it never slows the run down and never grows
memory without limit. The replay buffer lets a reconnecting tab catch up on what it missed
instead of showing a blank page until the next event.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

EventKind = Literal[
    "run.created",
    "run.started",
    "run.progress",
    "run.finished",
    "run.updated",
    "run.deleted",
    "queue.changed",
    "rating.changed",
    "vote.added",
    "comfy.status",
    "lab.message",
    "heartbeat",
]

DEFAULT_BUFFER = 400
DEFAULT_SUBSCRIBER_QUEUE = 200


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int = 0
    kind: EventKind
    at: float = Field(default_factory=time.time)
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        """The wire form: the envelope, with the payload nested under ``data``.

        Nesting is not decoration. Flattening ``data`` into the envelope let a publisher's
        own key shadow ``seq`` — and ``seq`` is what a reconnecting client sends back as
        ``?after=``, so a shadowed value made it replay or skip events on every reconnect.

        The frame is deliberately left unnamed. An `event:` field routes the frame to a
        listener of that name instead of `onmessage`, so naming it means every client must
        enumerate every kind — and a kind added later goes unheard, with the socket open and
        nothing to show for it. The kind is in the payload, which is where it is read.
        """
        payload = json.dumps(
            {
                "seq": self.seq,
                "kind": self.kind,
                "at": self.at,
                "run_id": self.run_id,
                "data": self.data,
            },
            ensure_ascii=False,
            default=str,
        )
        return f"id: {self.seq}\ndata: {payload}\n\n"


class Subscription:
    """One reader's view of the stream. Always close it, or use it as a context manager."""

    def __init__(self, bus: EventBus, maxsize: int = DEFAULT_SUBSCRIBER_QUEUE) -> None:
        self._bus = bus
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self.closed = False

    def offer(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # Drop the oldest so a live tab keeps seeing recent events rather than stalling.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass
            self.dropped += 1

    def get(self, timeout: float | None = None) -> Event | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> list[Event]:
        found: list[Event] = []
        while True:
            try:
                found.append(self._queue.get_nowait())
            except queue.Empty:
                return found

    def stream(self, *, heartbeat_s: float = 15.0) -> Iterator[Event]:
        """Yield events forever, with a heartbeat so idle proxies keep the socket open."""
        while not self.closed:
            event = self.get(timeout=heartbeat_s)
            if event is None:
                yield Event(kind="heartbeat", seq=self._bus.last_seq)
                continue
            yield event

    def close(self) -> None:
        self.closed = True
        self._bus.unsubscribe(self)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class EventBus:
    def __init__(self, *, buffer: int = DEFAULT_BUFFER) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Subscription] = []
        self._buffer: list[Event] = []
        self._buffer_size = buffer
        self._seq = 0

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(
        self,
        kind: EventKind,
        *,
        run_id: str | None = None,
        **data: Any,
    ) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(seq=self._seq, kind=kind, run_id=run_id, data=data)
            self._buffer.append(event)
            if len(self._buffer) > self._buffer_size:
                del self._buffer[: len(self._buffer) - self._buffer_size]
            targets = list(self._subscribers)
        for subscription in targets:
            subscription.offer(event)
        return event

    def subscribe(self, *, replay_after: int | None = None) -> Subscription:
        subscription = Subscription(self)
        with self._lock:
            self._subscribers.append(subscription)
            missed = (
                [event for event in self._buffer if event.seq > replay_after]
                if replay_after is not None
                else []
            )
        for event in missed:
            subscription.offer(event)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)

    def history(self, *, after: int = 0, limit: int = DEFAULT_BUFFER) -> list[Event]:
        with self._lock:
            return [event for event in self._buffer if event.seq > after][-limit:]

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
