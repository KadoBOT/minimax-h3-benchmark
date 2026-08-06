# bench/comfy.py
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


class ComfyError(RuntimeError):
    pass


# Friendly labels for common MiniMax H3 workflow node ids (UI graph).
NODE_LABELS: dict[str, str] = {
    "1": "UNET",
    "2": "CLIP",
    "3": "VideoVAE",
    "4": "AudioVAE",
    "5": "I2V cond",
    "6": "Scheduler",
    "7": "SamplerSelect",
    "8": "Guider",
    "10": "Sampler",
    "12": "AudioDecode",
    "15": "EasyCache",
    "20": "LoadImage",
    "91": "SageAttn",
    "92": "SolAttn",
    "98": "Resolution",
    "102": "Duration",
    "103": "FrameMath",
    "107": "Prompt",
    "110": "VideoCombine",
    "118": "Seed",
    "119": "Noise",
    "122": "Spectrum",
    "123": "SigmaShift",
    "124": "INT8 UNET",
    "125": "VAEDecode",
    "128": "H3Cache",
}


def node_label(node_id: str | int | None) -> str | None:
    if node_id is None:
        return None
    s = str(node_id)
    return NODE_LABELS.get(s, f"node {s}")


class ProgressCollector:
    """Collect ComfyUI WebSocket progress/executing events and derive s/it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (t, value, max, node, prompt_id)
        self._events: list[tuple[float, int, int, str | None, str | None]] = []
        self.current_node: str | None = None
        self.progress_value: int | None = None
        self.progress_max: int | None = None
        self._last_step_t: float | None = None
        self.instant_sec_per_it: float | None = None

    def on_progress(self, data: dict[str, Any]) -> None:
        try:
            value = int(data.get("value"))
            maximum = int(data.get("max"))
        except (TypeError, ValueError):
            return
        if maximum <= 0:
            return
        node = data.get("node")
        prompt_id = data.get("prompt_id")
        now = time.perf_counter()
        with self._lock:
            prev_t = self._last_step_t
            prev_v = self.progress_value
            self._events.append(
                (now, value, maximum, str(node) if node is not None else None, prompt_id)
            )
            self.progress_value = value
            self.progress_max = maximum
            if node is not None:
                self.current_node = str(node)
            # Instant s/it from last step advance (matches tqdm-style display)
            if prev_t is not None and prev_v is not None and value > prev_v:
                self.instant_sec_per_it = (now - prev_t) / (value - prev_v)
            self._last_step_t = now

    def on_executing(self, data: dict[str, Any]) -> None:
        node = data.get("node")
        with self._lock:
            if node is None:
                # node=None means the prompt finished executing
                self.current_node = None
            else:
                self.current_node = str(node)
                # entering a new node — step progress may not apply
                if self.progress_value is not None and self.progress_max is not None:
                    if self.progress_value >= self.progress_max:
                        self.progress_value = None
                        self.progress_max = None

    def live_snapshot(self) -> dict[str, Any]:
        with self._lock:
            node = self.current_node
            value = self.progress_value
            maximum = self.progress_max
            instant = self.instant_sec_per_it
        out: dict[str, Any] = {
            "node": node,
            "node_label": node_label(node),
        }
        if value is not None and maximum is not None:
            out["progress"] = f"{value}/{maximum}"
            out["progress_value"] = value
            out["progress_max"] = maximum
        if instant is not None:
            out["sec_per_it"] = round(instant, 3)
        return out

    def sec_per_it(self, prompt_id: str | None = None) -> float | None:
        """Average seconds per iteration for the dominant progress series.

        Prefer the node with the largest step count (usually the sampler).
        Uses mean inter-step deltas when value increases; falls back to
        (last_t - first_t) / last_value.
        """
        with self._lock:
            events = list(self._events)
        if prompt_id is not None:
            events = [e for e in events if e[4] == prompt_id]
        if len(events) < 2:
            return None

        by_node: dict[str, list[tuple[float, int, int]]] = {}
        for t, value, maximum, node, _pid in events:
            key = node or "_unknown"
            by_node.setdefault(key, []).append((t, value, maximum))

        # Pick series with the highest max (sampler steps)
        def series_key(xs: list[tuple[float, int, int]]) -> tuple[int, int]:
            return (max(m for _t, _v, m in xs), len(xs))

        series = max(by_node.values(), key=series_key)
        series = sorted(series, key=lambda x: x[0])

        deltas: list[float] = []
        for i in range(1, len(series)):
            t0, v0, _m0 = series[i - 1]
            t1, v1, _m1 = series[i]
            if v1 > v0:
                deltas.append((t1 - t0) / (v1 - v0))
        if deltas:
            return sum(deltas) / len(deltas)

        t0, v0, _m0 = series[0]
        t1, v1, _m1 = series[-1]
        if v1 > 0 and t1 > t0:
            return (t1 - t0) / v1
        return None


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout_s: float = 36000.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.client_id = str(uuid4())
        self.current_prompt_id: str | None = None

    def _request(self, method: str, path: str, data: dict | None = None, timeout: float | None = None) -> Any:
        url = f"{self.base_url}{path}"
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        to = timeout if timeout is not None else min(120.0, self.timeout_s)
        try:
            with urllib.request.urlopen(req, timeout=to) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise ComfyError(f"HTTP {e.code} {path}: {detail}") from e
        except urllib.error.URLError as e:
            raise ComfyError(f"Comfy unreachable at {self.base_url}: {e}") from e

    def system_stats(self) -> dict:
        return self._request("GET", "/system_stats")

    def interrupt(self) -> None:
        """Interrupt the currently executing ComfyUI job."""
        try:
            self._request("POST", "/interrupt", {}, timeout=10.0)
        except ComfyError:
            # Best-effort; Comfy may already be idle.
            pass

    def clear_queue(self) -> None:
        """Remove all pending (and typically running) items from the ComfyUI queue."""
        try:
            self._request("POST", "/queue", {"clear": True}, timeout=10.0)
        except ComfyError:
            pass

    def cancel_all(self) -> None:
        """Stop active work: interrupt current job and clear the queue."""
        self.interrupt()
        self.clear_queue()
        self.current_prompt_id = None

    def clear_execution_cache(self) -> None:
        """Clear ComfyUI node execution cache so the next identical prompt re-runs.

        Without this, a second run with the same seed/settings returns in ~0s
        because every node is cache-hit (warmup already produced outputs).
        Does NOT unload models / clean VRAM.
        """
        # Prefer standalone clear node if available.
        prompt = {
            "9001": {
                "class_type": "PRO_ClearCacheNode",
                "inputs": {"confirm": True},
            }
        }
        try:
            _pid, _elapsed, hist, _it = self.run_prompt(prompt, track=False)
            # If the node errored, fall through to secondary method.
            status = (hist.get("status") or {}).get("status_str")
            if status == "error":
                raise ComfyError("PRO_ClearCacheNode failed")
            return
        except ComfyError:
            pass

        # Fallback: easy clearCacheAll needs an anything input — use a no-op primitive.
        prompt = {
            "9001": {
                "class_type": "PrimitiveFloat",
                "inputs": {"value": 0.0},
            },
            "9002": {
                "class_type": "easy clearCacheAll",
                "inputs": {"anything": ["9001", 0]},
            },
        }
        try:
            self.run_prompt(prompt, track=False)
        except ComfyError as e:
            raise ComfyError(
                "Could not clear ComfyUI execution cache "
                "(need PRO_ClearCacheNode or easy clearCacheAll). "
                f"Original error: {e}"
            ) from e

    def queue_prompt(self, prompt: dict[str, Any]) -> str:
        payload = {"prompt": prompt, "client_id": self.client_id}
        out = self._request("POST", "/prompt", payload)
        if not out or "prompt_id" not in out:
            raise ComfyError(f"unexpected /prompt response: {out}")
        return out["prompt_id"]

    def get_history(self, prompt_id: str) -> dict | None:
        hist = self._request("GET", f"/history/{prompt_id}")
        if not hist:
            return None
        return hist.get(prompt_id)

    @staticmethod
    def _status_messages(item: dict) -> list:
        return (item.get("status") or {}).get("messages") or []

    @classmethod
    def was_node_cached(cls, history_item: dict, node_id: str | int) -> bool:
        nid = str(node_id)
        for msg in cls._status_messages(history_item):
            if not msg or msg[0] != "execution_cached":
                continue
            nodes = (msg[1] or {}).get("nodes") or []
            if nid in {str(n) for n in nodes}:
                return True
        return False

    def wait_for_prompt(self, prompt_id: str, poll_s: float = 1.0) -> dict:
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            item = self.get_history(prompt_id)
            if item is not None:
                status = item.get("status") or {}
                status_str = status.get("status_str")
                messages = status.get("messages") or []

                # Hard failures / interrupt
                if status_str == "error" or status_str == "interrupted":
                    raise ComfyError(f"prompt {prompt_id} {status_str}: {messages}")

                for msg in messages:
                    if not msg:
                        continue
                    kind = msg[0]
                    if kind in ("execution_error", "execution_interrupted"):
                        raise ComfyError(f"prompt {prompt_id} {kind}: {msg[1:]}")

                # Success: completed with outputs
                if status.get("completed") is True and "outputs" in item:
                    if status_str == "error":
                        raise ComfyError(f"prompt {prompt_id} failed: {status}")
                    return item

                # Some builds only set outputs without completed flag
                if "outputs" in item and status_str == "success":
                    return item

            time.sleep(poll_s)
        raise ComfyError(f"timeout waiting for prompt {prompt_id}")

    def download_output_file(
        self, filename: str, subfolder: str, folder_type: str, dest: Path
    ) -> Path:
        q = (
            f"/view?filename={urllib.parse.quote(filename)}"
            f"&subfolder={urllib.parse.quote(subfolder)}"
            f"&type={urllib.parse.quote(folder_type)}"
        )
        url = f"{self.base_url}{q}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return dest

    def find_first_video(self, history_item: dict) -> tuple[str, str, str] | None:
        outputs = history_item.get("outputs") or {}
        for _node_id, node_out in outputs.items():
            for key in ("gifs", "videos", "images"):
                for item in node_out.get(key) or []:
                    fn = item.get("filename") or ""
                    if fn.lower().endswith((".mp4", ".webm", ".gif")):
                        return fn, item.get("subfolder") or "", item.get("type") or "output"
        # fallback any file-like
        for _node_id, node_out in outputs.items():
            for _key, arr in node_out.items():
                if not isinstance(arr, list):
                    continue
                for item in arr:
                    if isinstance(item, dict) and item.get("filename"):
                        return (
                            item["filename"],
                            item.get("subfolder") or "",
                            item.get("type") or "output",
                        )
        return None

    def _ws_url(self) -> str:
        base = self.base_url
        if base.startswith("https://"):
            ws = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            ws = "ws://" + base[len("http://") :]
        else:
            ws = "ws://" + base
        return f"{ws}/ws?clientId={urllib.parse.quote(self.client_id)}"

    def _start_progress_listener(
        self,
        collector: ProgressCollector,
        on_live: Any | None = None,
    ) -> tuple[threading.Event, threading.Thread]:
        stop = threading.Event()

        def worker() -> None:
            try:
                import asyncio

                import websockets
            except ImportError:
                return

            async def listen() -> None:
                uri = self._ws_url()
                try:
                    async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
                        while not stop.is_set():
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            except asyncio.TimeoutError:
                                continue
                            except Exception:
                                break
                            if isinstance(raw, bytes):
                                # binary previews — ignore
                                continue
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            mtype = msg.get("type")
                            data = msg.get("data") or {}
                            if mtype == "progress":
                                collector.on_progress(data)
                                if on_live is not None:
                                    try:
                                        on_live(collector.live_snapshot())
                                    except Exception:
                                        pass
                            elif mtype == "executing":
                                collector.on_executing(data)
                                if on_live is not None:
                                    try:
                                        on_live(collector.live_snapshot())
                                    except Exception:
                                        pass

                except Exception:
                    return

            try:
                asyncio.run(listen())
            except Exception:
                return

        t = threading.Thread(target=worker, name="comfy-ws-progress", daemon=True)
        t.start()
        # Give the socket a moment to connect before we queue the prompt
        time.sleep(0.15)
        return stop, t

    def run_prompt(
        self,
        prompt: dict[str, Any],
        *,
        track: bool = True,
        on_live: Any | None = None,
    ) -> tuple[str, float, dict, float | None]:
        """Queue prompt and wait.

        Returns (prompt_id, elapsed_s, history_item, sec_per_it).
        *sec_per_it* is derived from WebSocket progress events (sampler s/it).
        *on_live* is called with live snapshots (node / progress / s/it) during the run.
        """
        collector = ProgressCollector()
        stop: threading.Event | None = None
        ws_thread: threading.Thread | None = None
        if track:
            stop, ws_thread = self._start_progress_listener(collector, on_live=on_live)

        t0 = time.perf_counter()
        pid = self.queue_prompt(prompt)
        if track:
            self.current_prompt_id = pid
        try:
            item = self.wait_for_prompt(pid)
        finally:
            if track and self.current_prompt_id == pid:
                self.current_prompt_id = None
            if stop is not None:
                stop.set()
            if ws_thread is not None:
                ws_thread.join(timeout=2.0)
        elapsed = time.perf_counter() - t0
        # Prefer average over the full sampling series; fall back to last instant
        sec_per_it = collector.sec_per_it(pid) if track else None
        if sec_per_it is None and track:
            sec_per_it = collector.instant_sec_per_it
        return pid, elapsed, item, sec_per_it
