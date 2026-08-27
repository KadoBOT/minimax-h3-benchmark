"""HTTP and WebSocket client for a running ComfyUI instance."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from h3lab.comfy.graph import Prompt
from h3lab.comfy.progress import PREVIEW_MESSAGE, ProgressTracker
from h3lab.comfy.studio import (
    STUDIO_API_ROOT,
    STUDIO_CONTRACT_VERSION,
    StudioContractError,
    response_error,
    validate_manifest,
    validate_prepare_response,
)

LiveCallback = Callable[[dict[str, Any]], None]

VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov", ".gif")
OUTPUT_KEYS = ("videos", "gifs")


class ComfyError(RuntimeError):
    """ComfyUI refused a request, or the request could not reach it."""


class ComfyUnreachable(ComfyError):
    pass


class PromptRejected(ComfyError):
    """The graph failed validation, so nothing was queued."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class PromptFailed(ComfyError):
    """The graph was queued and then failed, or was interrupted."""


class PromptTimeout(ComfyError):
    pass


class Outcome:
    """What came back from one execution."""

    __slots__ = ("prompt_id", "wall_s", "history", "sec_per_it", "steps")

    def __init__(
        self,
        prompt_id: str,
        wall_s: float,
        history: dict[str, Any],
        sec_per_it: float | None,
        steps: int | None,
    ) -> None:
        self.prompt_id = prompt_id
        self.wall_s = wall_s
        self.history = history
        self.sec_per_it = sec_per_it
        self.steps = steps

    def cached_nodes(self) -> set[str]:
        """Nodes ComfyUI reused from its own execution cache instead of running."""
        found: set[str] = set()
        for message in (self.history.get("status") or {}).get("messages") or []:
            if message and message[0] == "execution_cached":
                found.update(str(node) for node in (message[1] or {}).get("nodes") or [])
        return found

    def was_cached(self, node_id: str | int | None) -> bool:
        """Whether ComfyUI reused one node. A node nobody could name was not cached."""
        return node_id is not None and str(node_id) in self.cached_nodes()


def parse_combo(spec: Any) -> list[str]:
    """Read a ComfyUI combo descriptor in either of the two shapes it ships in.

    Current builds send ``["COMBO", {"options": [...]}]``; older ones send the option list
    as the first element. A bare string must not be iterated, or the options come back as
    individual letters.
    """
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    head, *rest = spec
    if isinstance(head, str) and head.upper() == "COMBO":
        meta = rest[0] if rest else {}
        if isinstance(meta, dict):
            options = meta.get("options") or meta.get("choices") or []
            return [str(value) for value in options if value is not None and str(value)]
        return []
    if isinstance(head, (list, tuple)):
        return [str(value) for value in head if value is not None and str(value)]
    return []


def _validation_message(payload: dict[str, Any]) -> str:
    """Turn ComfyUI's nested validation error into one readable line."""
    error = payload.get("error") or {}
    parts: list[str] = []
    if isinstance(error, dict) and error.get("message"):
        detail = error.get("details")
        parts.append(f"{error['message']}{f' — {detail}' if detail else ''}")
    for node_id, entry in (payload.get("node_errors") or {}).items():
        for item in (entry or {}).get("errors") or []:
            name = (item.get("extra_info") or {}).get("input_name")
            where = f"{node_id}.{name}" if name else str(node_id)
            parts.append(f"{where}: {item.get('message')} {item.get('details') or ''}".strip())
    return "; ".join(parts) or "ComfyUI rejected the graph without saying why"


class ComfyClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        *,
        run_timeout_s: float = 36_000.0,
        request_timeout_s: float = 60.0,
        connect_timeout_s: float = 3.0,
        client_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_timeout_s = run_timeout_s
        self.request_timeout_s = request_timeout_s
        self.connect_timeout_s = connect_timeout_s
        self.client_id = client_id or f"h3lab-{int(time.time() * 1000):x}"
        # Connecting and reading get separate budgets. A model that takes two minutes to
        # load still needs a long read, but a ComfyUI that is simply not there should be
        # reported in seconds rather than blocking the whole page.
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(request_timeout_s, connect=connect_timeout_s),
        )
        self._active_prompt: str | None = None

    def _timeout(self, read_s: float | None = None) -> httpx.Timeout:
        return httpx.Timeout(read_s or self.request_timeout_s, connect=self.connect_timeout_s)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ComfyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- plumbing ----------------------------------------------------------

    def _request_raw(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        try:
            return self._http.request(
                method, path, json=json_body, timeout=self._timeout(timeout)
            )
        except httpx.HTTPError as exc:
            raise ComfyUnreachable(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc

    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        timeout: float | None = None,
    ) -> Any:
        response = self._request_raw(
            method,
            path,
            json_body=json_body,
            timeout=timeout,
        )
        if response.status_code >= 400:
            body = response.text[:2000]
            raise ComfyError(f"HTTP {response.status_code} on {path}: {body}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    # --- status ------------------------------------------------------------

    def is_up(self) -> bool:
        try:
            self._call("GET", "/system_stats", timeout=3.0)
            return True
        except ComfyError:
            return False

    def system_stats(self) -> dict[str, Any]:
        return self._call("GET", "/system_stats") or {}

    def object_info(self, class_type: str) -> dict[str, Any]:
        return self._call("GET", f"/object_info/{class_type}") or {}

    def object_info_all(self) -> dict[str, Any]:
        """Every installed node class. Large — read it once and cache it."""
        return self._call("GET", "/object_info", timeout=120.0) or {}

    def combo_options(self, class_type: str, input_name: str) -> list[str]:
        """The dropdown values ComfyUI itself offers for one widget."""
        info = self.object_info(class_type).get(class_type) or {}
        for entries in (info.get("input") or {}).values():
            if not isinstance(entries, dict) or input_name not in entries:
                continue
            return parse_combo(entries[input_name])
        return []

    def studio_manifest(self) -> dict[str, Any]:
        path = f"{STUDIO_API_ROOT}/manifest"
        response = self._request_raw("GET", path)
        self._raise_studio_http_error(response, path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise StudioContractError(
                "contract_unavailable",
                "Studio manifest response is not valid JSON",
            ) from exc
        return validate_manifest(payload)

    def studio_component(self) -> tuple[bytes, str]:
        return self._studio_javascript("component.js")

    def studio_template_runtime(self) -> tuple[bytes, str]:
        return self._studio_javascript("template_runtime.mjs")

    def _studio_javascript(self, filename: str) -> tuple[bytes, str]:
        path = f"{STUDIO_API_ROOT}/{filename}"
        response = self._request_raw("GET", path)
        self._raise_studio_http_error(response, path)
        return response.content, response.headers.get(
            "content-type",
            "application/javascript",
        )

    def prepare_studio(
        self,
        workflow: dict[str, Any],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        path = f"{STUDIO_API_ROOT}/prepare"
        response = self._request_raw(
            "POST",
            path,
            json_body={
                "contract_version": STUDIO_CONTRACT_VERSION,
                "workflow": workflow,
                "inputs": inputs,
            },
        )
        self._raise_studio_http_error(response, path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise StudioContractError(
                "invalid_response",
                "Studio prepare response is not valid JSON",
            ) from exc
        return validate_prepare_response(payload)

    @staticmethod
    def _raise_studio_http_error(response: httpx.Response, path: str) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 404:
            raise StudioContractError(
                "contract_unavailable",
                "MiniMax H3 Studio contract v1 is not installed in ComfyUI",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("code"):
            raise response_error(
                payload,
                fallback=f"Studio request failed ({response.status_code})",
            )
        raise ComfyError(
            f"HTTP {response.status_code} on {path}: {response.text[:2000]}"
        )

    def models(self, folder: str) -> list[str]:
        """List model names available under a folder in ComfyUI (/models/{folder})."""
        try:
            data = self._call("GET", f"/models/{folder}")
            if isinstance(data, list):
                return [str(item) for item in data if item is not None]
        except ComfyError:
            pass
        return []

    # --- control -----------------------------------------------------------

    def interrupt(self) -> None:
        try:
            self._call("POST", "/interrupt", json_body={}, timeout=10.0)
        except ComfyError:
            pass  # already idle is not a failure

    def clear_queue(self) -> None:
        try:
            self._call("POST", "/queue", json_body={"clear": True}, timeout=10.0)
        except ComfyError:
            pass

    def cancel_all(self) -> None:
        self.interrupt()
        self.clear_queue()
        self._active_prompt = None

    def free(self, *, unload_models: bool = True, free_memory: bool = True) -> None:
        try:
            self._call(
                "POST",
                "/free",
                json_body={"unload_models": unload_models, "free_memory": free_memory},
                timeout=120.0,
            )
        except ComfyError:
            pass

    def clear_execution_cache(self) -> bool:
        """Force the next identical graph to actually sample instead of replaying outputs.

        ComfyUI memoizes node outputs, so re-running the same graph can return the previous
        tensors in about no time — which would make a timing number meaningless. Two node
        packs can do the clearing; whichever is installed wins.
        """
        attempts: tuple[Prompt, ...] = (
            {"9001": {"class_type": "PRO_ClearCacheNode", "inputs": {"confirm": True}}},
            {
                "9001": {"class_type": "PrimitiveFloat", "inputs": {"value": 0.0}},
                "9002": {"class_type": "easy clearCacheAll", "inputs": {"anything": ["9001", 0]}},
            },
        )
        for prompt in attempts:
            try:
                self.execute(prompt, track=False)
                return True
            except ComfyError:
                continue
        return False

    # --- queueing ----------------------------------------------------------

    def queue(self, prompt: Prompt, *, workflow: dict[str, Any] | None = None) -> str:
        """Submit *prompt*, optionally saying which editor graph it came from.

        ComfyUI hands `extra_data.extra_pnginfo` to any node that asks for it, and VHS writes
        every key of it into the PNG it saves beside the video. The `workflow` key is the one
        the frontend prefers when an image is dropped on the canvas, so sending it is the
        difference between reopening a run as its own graph and reopening it as API boxes.
        """
        payload: dict[str, Any] = {"prompt": prompt, "client_id": self.client_id}
        if workflow is not None:
            payload["extra_data"] = {"extra_pnginfo": {"workflow": workflow}}
        try:
            response = self._http.post("/prompt", json=payload, timeout=self._timeout())
        except httpx.HTTPError as exc:
            raise ComfyUnreachable(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc

        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                raise PromptRejected(f"HTTP {response.status_code}: {response.text[:2000]}") from None
            raise PromptRejected(_validation_message(detail), detail)

        body = response.json() if response.content else None
        if not isinstance(body, dict) or "prompt_id" not in body:
            raise ComfyError(f"unexpected /prompt response: {body}")
        return str(body["prompt_id"])

    def history(self, prompt_id: str) -> dict[str, Any] | None:
        payload = self._call("GET", f"/history/{prompt_id}")
        if not isinstance(payload, dict):
            return None
        entry = payload.get(prompt_id)
        return entry if isinstance(entry, dict) else None

    def recent_history(self, max_items: int = 50) -> dict[str, Any]:
        payload = self._call("GET", f"/history?max_items={int(max_items)}")
        return payload if isinstance(payload, dict) else {}

    def wait(self, prompt_id: str, *, poll_s: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + self.run_timeout_s
        while time.monotonic() < deadline:
            entry = self.history(prompt_id)
            if entry is not None:
                status = entry.get("status") or {}
                state = status.get("status_str")
                messages = status.get("messages") or []
                if state in ("error", "interrupted"):
                    raise PromptFailed(f"{state}: {_describe_messages(messages)}")
                for message in messages:
                    if message and message[0] in ("execution_error", "execution_interrupted"):
                        raise PromptFailed(f"{message[0]}: {_describe_messages([message])}")
                if "outputs" in entry and (status.get("completed") or state == "success"):
                    return entry
            time.sleep(poll_s)
        raise PromptTimeout(f"gave up waiting for prompt {prompt_id}")

    def execute(
        self,
        prompt: Prompt,
        *,
        track: bool = True,
        on_live: LiveCallback | None = None,
        workflow: dict[str, Any] | None = None,
        tracker: ProgressTracker | None = None,
    ) -> Outcome:
        """Queue one graph and wait for it, deriving the sampling rate while it runs."""
        tracker = tracker if tracker is not None else ProgressTracker.of(prompt)
        listener: _ProgressListener | None = None
        if track:
            listener = _ProgressListener(self._ws_url(), tracker, on_live)
            listener.start()

        started = time.perf_counter()
        try:
            prompt_id = self.queue(prompt, workflow=workflow)
        except ComfyError:
            if listener is not None:
                listener.stop()
            raise

        if track:
            self._active_prompt = prompt_id
        try:
            entry = self.wait(prompt_id)
        finally:
            if self._active_prompt == prompt_id:
                self._active_prompt = None
            if listener is not None:
                listener.stop()

        return Outcome(
            prompt_id=prompt_id,
            wall_s=time.perf_counter() - started,
            history=entry,
            sec_per_it=tracker.sec_per_it() if track else None,
            steps=tracker.steps_seen() if track else None,
        )

    # --- outputs -----------------------------------------------------------

    @staticmethod
    def find_video(history: dict[str, Any]) -> tuple[str, str, str] | None:
        outputs = history.get("outputs") or {}
        for node_output in outputs.values():
            for key in OUTPUT_KEYS:
                for item in node_output.get(key) or []:
                    name = str(item.get("filename") or "")
                    if name.lower().endswith(VIDEO_SUFFIXES):
                        return (
                            name,
                            str(item.get("subfolder") or ""),
                            str(item.get("type") or "output"),
                        )
        return None

    def download(self, filename: str, subfolder: str, folder_type: str, destination: Path) -> Path:
        query = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": folder_type}
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            stream = self._http.stream("GET", f"/view?{query}", timeout=self._timeout(600.0))
            with stream as response:
                if response.status_code >= 400:
                    raise ComfyError(f"HTTP {response.status_code} fetching {filename}")
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 16):
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise ComfyUnreachable(f"cannot download {filename}: {exc}") from exc
        return destination

    def upload_input(self, source: Path, *, subfolder: str = "") -> str:
        """Put a local file into ComfyUI's input folder and return the name it took."""
        files = {"image": (source.name, source.read_bytes())}
        data = {"overwrite": "true"}
        if subfolder:
            data["subfolder"] = subfolder
        try:
            response = self._http.post(
                "/upload/image", files=files, data=data, timeout=self._timeout(300.0)
            )
        except httpx.HTTPError as exc:
            raise ComfyUnreachable(f"cannot upload {source.name}: {exc}") from exc
        if response.status_code >= 400:
            raise ComfyError(f"HTTP {response.status_code} uploading {source.name}")
        body = response.json() if response.content else {}
        return str(body.get("name") or source.name)

    # --- websocket ---------------------------------------------------------

    def _ws_url(self) -> str:
        base = self.base_url
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        else:
            base = "ws://" + base
        return f"{base}/ws?clientId={urllib.parse.quote(self.client_id)}"


def _describe_messages(messages: Iterable[Any]) -> str:
    """Pull the human-readable part out of ComfyUI's status message tuples.

    The entries that explain a failure come first. ComfyUI logs the run's whole status
    history, so the exception is always last, behind `execution_start` and `execution_cached`
    — sixty-odd characters of bookkeeping that say nothing. Anything downstream that shortens
    the message for display would cut the reason and keep the noise.
    """
    explained: list[str] = []
    bare: list[str] = []
    for message in messages or []:
        if not message:
            continue
        kind = message[0] if isinstance(message, (list, tuple)) else str(message)
        payload = message[1] if isinstance(message, (list, tuple)) and len(message) > 1 else None
        if isinstance(payload, dict):
            text = (
                payload.get("exception_message")
                or payload.get("error")
                or payload.get("node_type")
                or ""
            )
            node = payload.get("node_id") or payload.get("node")
            where = f" at node {node}" if node else ""
            described = f"{kind}{where}: {text}".strip().rstrip(":")
            (explained if text else bare).append(described)
        elif payload is not None:
            explained.append(f"{kind}: {payload}")
        else:
            bare.append(str(kind))
    # Keep the silent entries as trailing context; they are still evidence of what ran.
    return " | ".join(explained + bare)[:2000] or "no detail reported"


class _ProgressListener:
    """Runs the WebSocket read loop on its own thread and feeds the tracker."""

    def __init__(
        self, url: str, tracker: ProgressTracker, on_live: LiveCallback | None = None
    ) -> None:
        self._url = url
        self._tracker = tracker
        self._on_live = on_live
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="h3lab-comfy-ws", daemon=True)
        self._thread.start()
        # Connect before the prompt is queued, or the first progress events are missed and
        # the rate is derived from a partial window.
        time.sleep(0.2)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            import asyncio

            import websockets
        except ImportError:
            return

        async def listen() -> None:
            try:
                async with websockets.connect(self._url, max_size=8 << 20) as socket:
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            return
                        if isinstance(raw, bytes):
                            self._on_binary(raw)
                            continue
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        self._handle(message)
            except Exception:
                return  # a dropped socket must never fail the run itself

        try:
            asyncio.run(listen())
        except Exception:
            return

    def _on_binary(self, frame: bytes) -> None:
        """A picture of the latent being sampled, if the graph asked ComfyUI to draw one."""
        if self._tracker.on_preview(frame):
            self._announce()

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        data = message.get("data") or {}
        if kind == "progress":
            self._tracker.on_progress(data)
        elif kind == "executing":
            self._tracker.on_executing(data)
        elif kind == PREVIEW_MESSAGE:
            if not self._tracker.on_preview_message(data):
                return
        else:
            return
        self._announce()

    def _announce(self) -> None:
        if self._on_live is not None:
            try:
                self._on_live(self._tracker.snapshot())
            except Exception:
                pass  # a slow or broken subscriber must not stop the read loop
