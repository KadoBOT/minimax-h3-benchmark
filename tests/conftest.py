from __future__ import annotations

import base64
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from h3lab.comfy.client import Outcome  # noqa: E402
from h3lab.comfy.progress import SAMPLER_CLASSES  # noqa: E402
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
        self.workflows: list[dict[str, Any] | None] = []
        self.progress: list[dict[str, Any]] = []
        self.cache_clears = 0
        self.cancels = 0
        self.object_info_reads = 0
        self.raise_on_execute: Exception | None = None
        # A picture to send the way the preview override node does, for the tests that care.
        # Left unset, this stub says nothing on that channel, exactly like a graph with no
        # preview override in it.
        self.preview_image: bytes | None = None
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

    def object_info_all(self) -> dict[str, Any]:
        """No schemas: this stub is the offline case, and the lab must build anyway."""
        self.object_info_reads += 1
        return {}

    def combo_options(self, class_type: str, input_name: str) -> list[str]:
        return []

    def models(self, folder: str) -> list[str]:
        return []

    def is_up(self) -> bool:
        return True

    def execute(
        self, prompt, *, track: bool = True, on_live=None, workflow=None, tracker=None
    ) -> Outcome:
        self.submitted.append(prompt)
        self.workflows.append(workflow)
        if on_live is not None:
            # Report progress the way ComfyUI does — by node id, through the tracker — so the
            # labels a browser receives are the ones the real path would produce.
            node = next(
                (
                    node_id
                    for node_id, node in prompt.items()
                    if node["class_type"] in SAMPLER_CLASSES
                ),
                next(iter(prompt), "1"),
            )
            if tracker is None:
                snapshot = {"node": node, "step": 1, "step_total": 20}
            else:
                tracker.on_executing({"node": node})
                tracker.on_progress({"node": node, "value": 1, "max": 20})
                if self.preview_image is not None:
                    tracker.on_preview_message(
                        {
                            "image": base64.b64encode(self.preview_image).decode(),
                            "mime": "image/jpeg",
                            "step": 1,
                            "total": 20,
                        }
                    )
                snapshot = tracker.snapshot()
            snapshot.setdefault("sec_per_it", self.sec_per_it)
            self.progress.append(dict(snapshot))
            on_live(snapshot)
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
