# bench/comfy.py
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


class ComfyError(RuntimeError):
    pass


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
            pid, _elapsed, hist = self.run_prompt(prompt, track=False)
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

    def run_prompt(
        self, prompt: dict[str, Any], *, track: bool = True
    ) -> tuple[str, float, dict]:
        """Queue prompt and wait. Returns (prompt_id, elapsed_s, history_item)."""
        t0 = time.perf_counter()
        pid = self.queue_prompt(prompt)
        if track:
            self.current_prompt_id = pid
        try:
            item = self.wait_for_prompt(pid)
        finally:
            if track and self.current_prompt_id == pid:
                self.current_prompt_id = None
        elapsed = time.perf_counter() - t0
        return pid, elapsed, item
