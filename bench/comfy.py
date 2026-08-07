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
    """Derive ComfyUI **s/it** (seconds per iteration) from WebSocket events.

    Matches Comfy tqdm: wall time while the sampler-like node ran ÷ step count.

    Do **not** use inter-arrival times of progress messages alone — they often
    arrive in a burst at the end (buffered), which produces bogus ~0.01 s/it
    and inverted nonsense when shown as it/s.
    """

    # Prefer the advanced sampler node when present (MiniMax H3 workflow).
    PREFERRED_SAMPLER_NODES = frozenset({"10"})

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current_node: str | None = None
        self.progress_value: int | None = None
        self.progress_max: int | None = None
        # First wall-clock touch for a node (executing preferred; never reset mid-run)
        self._node_enter: dict[str, float] = {}
        self._node_max: dict[str, int] = {}
        self._node_last_value: dict[str, int] = {}
        self._node_finalized: set[str] = set()
        # Best finalized s/it (prefer higher step counts = real sampler)
        self._best_sec_per_it: float | None = None
        self._best_steps: int = 0
        self.instant_sec_per_it: float | None = None

    def _is_plausible(self, duration: float, steps: int) -> bool:
        """Reject burst-delivery artefacts (e.g. 20 steps in 0.17s → 0.008 s/it)."""
        if steps <= 0 or duration <= 0:
            return False
        # Multi-step sampling cannot finish in a few hundred ms of wall time.
        if steps >= 8 and duration < max(1.0, 0.15 * steps):
            return False
        candidate = duration / steps
        # Sub-20ms/it on many steps is almost always WS buffering, not real denoise.
        if steps >= 8 and candidate < 0.05:
            return False
        return True

    def _consider(self, node: str, end_t: float) -> None:
        enter = self._node_enter.get(node)
        steps = self._node_max.get(node) or 0
        if enter is None or steps <= 0:
            return
        duration = end_t - enter
        if not self._is_plausible(duration, steps):
            return
        candidate = duration / steps
        prefer_node = node in self.PREFERRED_SAMPLER_NODES
        better_steps = steps > self._best_steps
        same_steps_slower = (
            steps == self._best_steps
            and self._best_sec_per_it is not None
            and candidate > self._best_sec_per_it
        )
        # Prefer more steps (sampler). On equal steps keep the *slower* rate —
        # burst finalize is too fast; a longer wall is more trustworthy.
        # Always allow preferred sampler node to replace a non-sampler winner
        # with fewer-or-equal steps.
        if self._best_sec_per_it is None or better_steps or same_steps_slower:
            self._best_sec_per_it = candidate
            self._best_steps = steps
        elif prefer_node and steps >= self._best_steps:
            self._best_sec_per_it = candidate
            self._best_steps = steps

    def _finalize_node(self, node: str, end_t: float) -> None:
        if node in self._node_finalized:
            # Still allow a later (longer) plausible reading to win
            self._consider(node, end_t)
            return
        self._consider(node, end_t)
        if node in self._node_enter and self._node_max.get(node, 0) > 0:
            # Only mark finalized if we had a plausible reading or enough wall time
            enter = self._node_enter[node]
            steps = self._node_max[node]
            duration = end_t - enter
            if self._is_plausible(duration, steps) or duration >= 1.0:
                self._node_finalized.add(node)

    def on_progress(self, data: dict[str, Any]) -> None:
        try:
            value = int(data.get("value"))
            maximum = int(data.get("max"))
        except (TypeError, ValueError):
            return
        if maximum <= 0:
            return
        raw_node = data.get("node")
        now = time.perf_counter()
        with self._lock:
            node = str(raw_node) if raw_node is not None else self.current_node
            if node is None:
                return
            # Start clock only once. Prefer executing-based enter; progress only
            # seeds enter when value is still 0 (model init) or 1 (first step).
            if node not in self._node_enter:
                if value <= 1:
                    self._node_enter[node] = now
                # else: late/burst progress without enter — ignore for clock start
            self.current_node = node
            self.progress_value = value
            self.progress_max = maximum
            self._node_max[node] = max(self._node_max.get(node, 0), maximum)
            self._node_last_value[node] = value
            enter = self._node_enter.get(node)
            if enter is not None and value > 0 and now > enter:
                # Live tqdm-style estimate (may include model-init if enter was early)
                est = (now - enter) / value
                if self._is_plausible(now - enter, max(value, 1)) or value < 8:
                    self.instant_sec_per_it = est
            # Do NOT finalize on value==max alone — burst delivery hits max with
            # near-zero wall. Finalize on executing leave instead.

    def on_executing(self, data: dict[str, Any]) -> None:
        raw = data.get("node")
        now = time.perf_counter()
        with self._lock:
            prev = self.current_node
            if prev is not None and (raw is None or str(raw) != prev):
                self._finalize_node(prev, now)
                self.progress_value = None
                self.progress_max = None
            if raw is None:
                self.current_node = None
                return
            node = str(raw)
            self.current_node = node
            # First enter only — never reset mid-node (re-sent executing events)
            if node not in self._node_enter:
                self._node_enter[node] = now

    def live_snapshot(self) -> dict[str, Any]:
        with self._lock:
            node = self.current_node
            value = self.progress_value
            maximum = self.progress_max
            instant = self.instant_sec_per_it
            best = self._best_sec_per_it
        out: dict[str, Any] = {
            "node": node,
            "node_label": node_label(node),
        }
        if value is not None and maximum is not None:
            out["progress"] = f"{value}/{maximum}"
            out["progress_value"] = value
            out["progress_max"] = maximum
        # Prefer best finalized; else live estimate. Unit is always s/it.
        rate = best if best is not None else instant
        if rate is not None and rate > 0:
            out["sec_per_it"] = round(rate, 3)
        return out

    def sec_per_it(self, prompt_id: str | None = None) -> float | None:
        """Sampler s/it for the finished prompt (seconds per iteration)."""
        del prompt_id
        with self._lock:
            if self.current_node is not None:
                self._finalize_node(self.current_node, time.perf_counter())
            # Also re-consider all known nodes (in case leave event was missed)
            now = time.perf_counter()
            for node in list(self._node_enter.keys()):
                self._consider(node, now)
            best = self._best_sec_per_it
            instant = self.instant_sec_per_it
            steps = self._best_steps
        if best is not None and best > 0 and steps >= 1:
            return best
        # Live fallback only if plausible multi-step estimate
        if instant is not None and instant >= 0.05:
            return instant
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
        """Clear ComfyUI **graph execution** cache (node output memoization).

        Call this **once after warmup, before the timed gen of the same cell**.
        That forces a real second sampling pass with the same seed/settings.

        This does **not**:
        - unload models / clean VRAM
        - disable EasyCache / Spectrum / H3 (those re-apply on real sampling)

        Without this, Comfy often returns the warmup tensors in ~0s and ``timed_s``
        is meaningless.
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
        # s/it only from ProgressCollector (plausibility-filtered). Do not fall
        # back to raw instant — that is where burst-WS ~0.01 s/it came from.
        sec_per_it = collector.sec_per_it(pid) if track else None
        return pid, elapsed, item, sec_per_it
