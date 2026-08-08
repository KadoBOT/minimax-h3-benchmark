from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from h3lab.comfy.client import Outcome  # noqa: E402
from h3lab.domain.config import GenerationConfig  # noqa: E402
from h3lab.settings import Settings  # noqa: E402


@pytest.fixture
def base_config() -> GenerationConfig:
    return GenerationConfig(
        mode="flf2v",
        diffusion_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        prompt="a courier on a magnetic skateboard",
        first_frame="frame.png",
        steps=20,
        seed=42,
    )


@pytest.fixture
def t2v_config() -> GenerationConfig:
    return GenerationConfig(mode="t2v", prompt="a quiet street at dawn")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    made = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=tmp_path / "comfy-input",
        web_dist=tmp_path / "web-dist",
    )
    made.ensure_dirs()
    made.models_dir.mkdir(parents=True, exist_ok=True)
    made.comfy_input_dir.mkdir(parents=True, exist_ok=True)
    return made


class StubComfy:
    """A ComfyUI stand-in the tests can steer.

    It answers the same surface the runner uses, so the worker loop under test is the real
    one; only the GPU on the other end of the socket is imaginary.
    """

    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.cache_clears = 0
        self.cancels = 0
        self.raise_on_execute: Exception | None = None
        self.sec_per_it: float | None = 8.5
        self.video_bytes = b"stub video payload"
        self.downloads: list[str] = []
        self.block = threading.Event()
        self.block.set()

    def clear_execution_cache(self) -> bool:
        self.cache_clears += 1
        return True

    def cancel_all(self) -> None:
        self.cancels += 1
        self.block.set()

    def execute(self, prompt, *, track: bool = True, on_live=None) -> Outcome:
        self.submitted.append(prompt)
        if on_live is not None:
            on_live({"node": "10", "step": 1, "step_total": 20, "sec_per_it": self.sec_per_it})
        self.block.wait(timeout=10.0)
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        return Outcome(
            prompt_id="stub-1",
            wall_s=170.0,
            history={
                "status": {"status_str": "success", "completed": True, "messages": []},
                "outputs": {
                    "110": {"gifs": [{"filename": "stub.mp4", "subfolder": "h3lab", "type": "output"}]}
                },
            },
            sec_per_it=self.sec_per_it,
            steps=20,
        )

    def download(self, filename, subfolder, folder_type, destination: Path) -> Path:
        self.downloads.append(filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.video_bytes)
        return destination

    @staticmethod
    def find_video(history):
        from h3lab.comfy.client import ComfyClient

        return ComfyClient.find_video(history)

    def close(self) -> None:
        pass


@pytest.fixture
def stub() -> StubComfy:
    return StubComfy()


@pytest.fixture
def lab_settings(tmp_path: Path) -> Settings:
    """A temp data dir and input folder, but the repository's real workflow templates."""
    made = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=tmp_path / "comfy-input",
        web_dist=tmp_path / "web-dist",
        comfy_url="http://127.0.0.1:9",
    )
    made.ensure_dirs()
    made.comfy_input_dir.mkdir(parents=True, exist_ok=True)
    (made.comfy_input_dir / "frame.png").write_bytes(b"")
    return made
