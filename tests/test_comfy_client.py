"""Client behaviour against a real HTTP server that imitates ComfyUI."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, urlparse

import pytest

from h3lab.comfy.catalog import (
    Catalog,
    InstalledNameError,
    build_catalog,
    default_model,
    is_h3_model,
    list_models,
    match_installed,
)
from h3lab.comfy.client import (
    ComfyClient,
    ComfyUnreachable,
    PromptFailed,
    PromptRejected,
    PromptTimeout,
    _describe_messages,
)
from h3lab.domain.config import (
    BASELINE_FIRST_FRAME,
    BASELINE_REF_IMAGES,
    DEFAULT_TURBO_LORA,
    DEFAULT_TURBO_STRENGTH,
)
from h3lab.settings import Settings

VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42 not a real video but a real payload"


class FakeComfy:
    """State a handler can mutate so a test can script ComfyUI's answers."""

    def __init__(self) -> None:
        self.queued: list[dict[str, Any]] = []
        self.history: dict[str, Any] = {}
        self.prompt_status: int = 200
        self.prompt_body: Any = {"prompt_id": "p1", "number": 1}
        self.interrupts = 0
        self.queue_clears = 0
        self.uploads: list[str] = []
        self.object_info: dict[str, Any] = {}


def _handler_for(state: FakeComfy):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            pass

        def _send(self, status: int, payload: Any, *, raw: bytes | None = None) -> None:
            body = raw if raw is not None else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/system_stats":
                self._send(200, {"system": {"comfyui_version": "test"}})
            elif path.startswith("/object_info/"):
                name = path.rsplit("/", 1)[-1]
                self._send(200, state.object_info.get(name, {}))
            elif path.startswith("/history/"):
                prompt_id = path.rsplit("/", 1)[-1]
                entry = state.history.get(prompt_id)
                self._send(200, {prompt_id: entry} if entry else {})
            elif path == "/history":
                self._send(200, state.history)
            elif path == "/view":
                query = parse_qs(parsed.query)
                if query.get("filename", [""])[0]:
                    self._send(200, None, raw=VIDEO_BYTES)
                else:
                    self._send(404, {"error": "not found"})
            else:
                self._send(404, {"error": f"no route {path}"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            path = urlparse(self.path).path
            if path == "/prompt":
                state.queued.append(json.loads(raw or b"{}"))
                self._send(state.prompt_status, state.prompt_body)
            elif path == "/interrupt":
                state.interrupts += 1
                self._send(200, {})
            elif path == "/queue":
                state.queue_clears += 1
                self._send(200, {})
            elif path == "/free":
                self._send(200, {})
            elif path == "/upload/image":
                state.uploads.append(str(len(raw)))
                self._send(200, {"name": "uploaded.png", "subfolder": ""})
            else:
                self._send(404, {"error": f"no route {path}"})

    return Handler


@pytest.fixture
def comfy() -> Iterator[tuple[FakeComfy, str]]:
    state = FakeComfy()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(state))
    # A short poll interval keeps teardown from costing half a second per test.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.daemon = True
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield state, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


@pytest.fixture
def client(comfy) -> Iterator[ComfyClient]:
    _state, url = comfy
    with ComfyClient(url, run_timeout_s=5.0, request_timeout_s=5.0) as made:
        yield made


def succeeded(prompt_id: str = "p1") -> dict[str, Any]:
    return {
        "status": {"status_str": "success", "completed": True, "messages": []},
        "outputs": {
            "110": {
                "gifs": [
                    {"filename": "out.mp4", "subfolder": "h3lab", "type": "output"}
                ]
            }
        },
    }


# --- reachability ----------------------------------------------------------


def test_is_up_is_true_for_a_live_instance(client):
    assert client.is_up() is True
    assert "comfyui_version" in client.system_stats()["system"]


def test_is_up_is_false_for_a_dead_port():
    with ComfyClient("http://127.0.0.1:9", request_timeout_s=0.3) as client:
        assert client.is_up() is False


def test_a_dead_port_raises_a_named_error():
    with ComfyClient("http://127.0.0.1:9", request_timeout_s=0.3) as client:
        with pytest.raises(ComfyUnreachable):
            client.queue({"1": {"class_type": "X", "inputs": {}}})


# --- queueing --------------------------------------------------------------


def test_queue_sends_the_graph_and_returns_the_prompt_id(comfy, client):
    state, _url = comfy
    prompt_id = client.queue({"1": {"class_type": "PrimitiveFloat", "inputs": {"value": 1.0}}})
    assert prompt_id == "p1"
    assert state.queued[0]["prompt"]["1"]["class_type"] == "PrimitiveFloat"
    assert state.queued[0]["client_id"] == client.client_id


def test_a_submitted_workflow_travels_as_png_metadata(comfy, client):
    """VHS writes every `extra_pnginfo` key into the PNG it saves beside the video.

    Without this the only chunk written is `prompt`, the API format — which ComfyUI can open,
    as a wall of unpositioned boxes. The `workflow` key is what makes the saved image open as
    the graph a person would recognise.
    """
    state, _url = comfy
    workflow = {"nodes": [{"id": 1, "type": "PrimitiveFloat"}], "links": []}
    client.queue({"1": {"class_type": "PrimitiveFloat", "inputs": {}}}, workflow=workflow)
    assert state.queued[0]["extra_data"]["extra_pnginfo"]["workflow"] == workflow


def test_a_submission_without_a_workflow_sends_no_metadata_block(comfy, client):
    state, _url = comfy
    client.queue({"1": {"class_type": "PrimitiveFloat", "inputs": {}}})
    assert "extra_data" not in state.queued[0]


def test_execute_forwards_the_workflow_it_was_given(comfy, client):
    state, _url = comfy
    state.history["p1"] = succeeded()
    workflow = {"nodes": [], "links": []}
    client.execute({"1": {"class_type": "X", "inputs": {}}}, track=False, workflow=workflow)
    assert state.queued[0]["extra_data"]["extra_pnginfo"]["workflow"] == workflow


def test_a_rejected_graph_reports_which_node_and_input_failed(comfy, client):
    state, _url = comfy
    state.prompt_status = 400
    state.prompt_body = {
        "error": {"message": "Prompt outputs failed validation", "details": ""},
        "node_errors": {
            "20": {
                "errors": [
                    {
                        "message": "Value not in list",
                        "details": "image: 'gone.png' not in []",
                        "extra_info": {"input_name": "image"},
                    }
                ]
            }
        },
    }
    with pytest.raises(PromptRejected) as caught:
        client.queue({"20": {"class_type": "LoadImage", "inputs": {"image": "gone.png"}}})
    message = str(caught.value)
    assert "20.image" in message
    assert "Value not in list" in message
    assert caught.value.detail["node_errors"]["20"]


# --- waiting ---------------------------------------------------------------


def test_execute_returns_the_history_entry_on_success(comfy, client):
    state, _url = comfy
    state.history["p1"] = succeeded()
    outcome = client.execute({"1": {"class_type": "X", "inputs": {}}}, track=False)
    assert outcome.prompt_id == "p1"
    assert outcome.wall_s >= 0
    assert outcome.history["outputs"]["110"]["gifs"][0]["filename"] == "out.mp4"


def test_an_execution_error_is_raised_with_its_detail(comfy, client):
    state, _url = comfy
    state.history["p1"] = {
        "status": {
            "status_str": "error",
            "completed": False,
            "messages": [
                [
                    "execution_error",
                    {
                        "node_id": "10",
                        "node_type": "SamplerCustomAdvanced",
                        "exception_message": "CUDA out of memory",
                    },
                ]
            ],
        }
    }
    with pytest.raises(PromptFailed) as caught:
        client.execute({"1": {"class_type": "X", "inputs": {}}}, track=False)
    assert "CUDA out of memory" in str(caught.value)
    assert "node 10" in str(caught.value)


def test_the_cause_of_a_failure_leads_the_message():
    """ComfyUI's status log buries the reason behind bookkeeping. It has to come first.

    A real failure arrived as `execution_start | execution_cached | execution_error at node
    122: bootstrap_first_forecast requires warmup_steps <= 1`. Neither of the first two
    entries says anything, and they cost 60 characters — enough that the run card's cap cut
    the message at `warmup_steps`, hiding the one number that explained the failure.
    """
    described = _describe_messages(
        [
            ["execution_start", {"prompt_id": "abc", "timestamp": 1}],
            ["execution_cached", {"nodes": ["1", "2"], "prompt_id": "abc"}],
            [
                "execution_error",
                {
                    "node_id": "122",
                    "node_type": "SpectrumApplyMiniMaxH3",
                    "exception_message": "bootstrap_first_forecast requires warmup_steps <= 1",
                },
            ],
        ]
    )
    assert described.startswith("execution_error at node 122:")
    # Truncating the head at any sane width must still leave the reason legible.
    assert "warmup_steps <= 1" in described[:120]
    # The silent entries are still evidence of what ran, so they are kept as trailing context.
    assert "execution_cached" in described


def test_a_failure_with_no_explanation_still_reports_what_happened():
    """Dropping the silent entries must not leave an empty message."""
    described = _describe_messages(
        [["execution_start", {"prompt_id": "abc"}], ["execution_interrupted", {}]]
    )
    assert "execution_interrupted" in described


def test_waiting_gives_up_instead_of_hanging(comfy):
    _state, url = comfy
    with ComfyClient(url, run_timeout_s=0.6, request_timeout_s=2.0) as client:
        with pytest.raises(PromptTimeout):
            client.execute({"1": {"class_type": "X", "inputs": {}}}, track=False)


def test_cached_nodes_are_reported(comfy, client):
    state, _url = comfy
    entry = succeeded()
    entry["status"]["messages"] = [["execution_cached", {"nodes": ["1", 10, "125"]}]]
    state.history["p1"] = entry
    outcome = client.execute({"1": {"class_type": "X", "inputs": {}}}, track=False)
    assert outcome.was_cached(10) is True
    assert outcome.was_cached("1") is True
    assert outcome.was_cached(999) is False


# --- outputs ---------------------------------------------------------------


def test_the_first_video_is_found_among_the_outputs():
    history = {
        "outputs": {
            "111": {"images": [{"filename": "poster.png", "type": "output"}]},
            "110": {"gifs": [{"filename": "clip.mp4", "subfolder": "h3lab", "type": "output"}]},
        }
    }
    assert ComfyClient.find_video(history) == ("clip.mp4", "h3lab", "output")


def test_still_images_and_non_video_outputs_are_not_video_results():
    history = {
        "outputs": {
            "preview": {"images": [{"filename": "preview.png", "type": "temp"}]},
            "latent": {"latents": [{"filename": "x.latent", "type": "output"}]},
        },
    }
    assert ComfyClient.find_video(history) is None


def test_no_outputs_means_no_video():
    assert ComfyClient.find_video({"outputs": {}}) is None


def test_download_writes_the_bytes_to_disk(client, tmp_path: Path):
    destination = tmp_path / "nested" / "clip.mp4"
    written = client.download("out.mp4", "h3lab", "output", destination)
    assert written == destination
    assert destination.read_bytes() == VIDEO_BYTES


def test_upload_returns_the_stored_name(client, tmp_path: Path):
    source = tmp_path / "frame.png"
    source.write_bytes(b"pixels")
    assert client.upload_input(source) == "uploaded.png"


# --- control ---------------------------------------------------------------


def test_cancel_all_interrupts_and_clears(comfy, client):
    state, _url = comfy
    client.cancel_all()
    assert state.interrupts == 1
    assert state.queue_clears == 1


def test_control_calls_never_raise_when_comfy_is_down():
    with ComfyClient("http://127.0.0.1:9", request_timeout_s=0.3) as client:
        client.cancel_all()  # must not raise
        client.free()


def test_clearing_the_execution_cache_reports_failure_when_no_node_pack_exists(comfy, client):
    state, _url = comfy
    state.history.clear()
    with ComfyClient(client.base_url, run_timeout_s=0.4, request_timeout_s=2.0) as quick:
        assert quick.clear_execution_cache() is False


def test_clearing_the_execution_cache_succeeds_when_the_node_exists(comfy, client):
    state, _url = comfy
    state.history["p1"] = succeeded()
    assert client.clear_execution_cache() is True
    assert state.queued[0]["prompt"]["9001"]["class_type"] == "PRO_ClearCacheNode"


# --- combo options ---------------------------------------------------------


def test_combo_options_read_the_current_comfy_format(comfy, client):
    state, _url = comfy
    state.object_info["KSamplerSelect"] = {
        "KSamplerSelect": {
            "input": {
                "required": {"sampler_name": ["COMBO", {"options": ["euler", "heun"]}]}
            }
        }
    }
    assert client.combo_options("KSamplerSelect", "sampler_name") == ["euler", "heun"]


def test_combo_options_read_the_legacy_comfy_format(comfy, client):
    state, _url = comfy
    state.object_info["BasicScheduler"] = {
        "BasicScheduler": {
            "input": {"required": {"scheduler": [["simple", "beta57"], {"default": "simple"}]}}
        }
    }
    assert client.combo_options("BasicScheduler", "scheduler") == ["simple", "beta57"]


def test_an_unknown_widget_yields_no_options(client):
    assert client.combo_options("Nothing", "nope") == []


# --- catalog ---------------------------------------------------------------


def test_model_names_must_mention_both_minimax_and_h3():
    assert is_h3_model("minimax_h3_fl2va_pruned_nvfp4.safetensors") is True
    assert is_h3_model("MiniMax-H3-FL2VA-Q4_K_M.gguf") is True
    assert is_h3_model("wan22_i2v.safetensors") is False
    assert is_h3_model("minimax_remover.safetensors") is False


def test_models_are_listed_from_disk_and_a_default_is_chosen(tmp_path: Path):
    directory = tmp_path / "diffusion_models"
    h3 = directory / "minimax-h3"
    other = directory / "other"
    h3.mkdir(parents=True)
    other.mkdir()
    for name in (
        "MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors",
        "custom_variant.safetensors",
        "notes.txt",
    ):
        (h3 / name).write_bytes(b"")
    (other / "minimax_h3_wrong_folder.safetensors").write_bytes(b"")
    found = list_models(directory)
    assert found == [
        "minimax-h3/custom_variant.safetensors",
        "minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors",
    ]
    assert list_models(h3) == found
    assert default_model(found) == (
        "minimax-h3/custom_variant.safetensors"
    )


def test_a_missing_models_folder_is_not_an_error(tmp_path: Path):
    assert list_models(tmp_path / "nope") == []
    assert default_model([]) == ""


def test_the_catalog_falls_back_when_comfy_is_offline(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=tmp_path / "input",
        comfy_url="http://127.0.0.1:9",
    )
    catalog = build_catalog(settings)
    assert catalog.comfy_online is False
    assert catalog.source == "fallback"
    assert "euler" in catalog.samplers
    assert catalog.diffusion_models_source == "unavailable"
    assert catalog.diffusion_models == []
    assert catalog.default_diffusion_model == ""
    assert catalog.defaults["diffusion_model"] == ""
    assert "nvfp4" not in str(catalog.model_dump()).lower()
    assert catalog.reference_limits == {"images": 9, "videos": 3, "audios": 3}


def test_an_offline_catalog_reads_the_minimax_h3_subfolder(tmp_path: Path):
    models = tmp_path / "diffusion_models"
    h3 = models / "minimax-h3"
    h3.mkdir(parents=True)
    (h3 / "MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors").write_bytes(b"")
    (h3 / "creator_variant.safetensors").write_bytes(b"")

    catalog = build_catalog(
        Settings(
            data_dir=tmp_path / "data",
            models_dir=models,
            comfy_input_dir=tmp_path / "input",
            comfy_url="http://127.0.0.1:9",
        )
    )

    assert catalog.diffusion_models_source == "disk"
    assert catalog.diffusion_models == [
        "minimax-h3/creator_variant.safetensors",
        "minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors",
    ]
    assert catalog.default_diffusion_model in catalog.diffusion_models
    assert catalog.defaults["diffusion_model"] == catalog.default_diffusion_model


def test_match_installed_keeps_a_folder_prefixed_combo_value():
    offered = ["minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors"]
    assert (
        match_installed("minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors", offered)
        == offered[0]
    )


def test_match_installed_finds_a_bare_name_in_the_live_folder():
    offered = ["minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors"]
    assert (
        match_installed("minimax_h3_fl2va_pruned_int8_convrot.safetensors", offered) == offered[0]
    )


def test_match_installed_refuses_a_checkpoint_comfy_does_not_have():
    offered = ["minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors"]
    with pytest.raises(InstalledNameError, match="nvfp4") as err:
        match_installed("minimax_h3_fl2va_pruned_nvfp4.safetensors", offered)
    assert "int8_convrot" in str(err.value)


def test_the_catalog_takes_unet_names_from_the_running_server(comfy, tmp_path: Path):
    """A models folder that exists but is empty is not a source of truth.

    ComfyUI's extra_model_paths.yaml is where the weights actually live, and
    only /object_info knows the combo values it will accept.
    """
    state, url = comfy
    state.object_info["UNETLoader"] = {
        "UNETLoader": {
            "input": {
                "required": {
                    "unet_name": [
                        [
                            "krea2/krea2_turbo-int4_convrot.safetensors",
                            "other/minimax_h3_wrong_folder.safetensors",
                            "minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors",
                        ],
                        {},
                    ]
                }
            }
        }
    }
    state.object_info["BasicScheduler"] = {
        "BasicScheduler": {"input": {"required": {"scheduler": [["beta57"], {}]}}}
    }
    state.object_info["KSamplerSelect"] = {
        "KSamplerSelect": {"input": {"required": {"sampler_name": [["euler"], {}]}}}
    }
    empty_models = tmp_path / "models"
    empty_models.mkdir()
    (tmp_path / "input").mkdir()
    catalog = build_catalog(
        Settings(
            data_dir=tmp_path / "data",
            models_dir=empty_models,
            comfy_input_dir=tmp_path / "input",
            comfy_url=url,
        )
    )
    assert catalog.diffusion_models_source == "comfy"
    assert catalog.diffusion_models == [
        "minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors"
    ]
    assert catalog.default_diffusion_model == (
        "minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors"
    )
    assert catalog.defaults["diffusion_model"] == catalog.default_diffusion_model


def test_the_local_minimax_h3_folder_wins_over_stale_live_entries(comfy, tmp_path: Path):
    state, url = comfy
    state.object_info["UNETLoader"] = {
        "UNETLoader": {
            "input": {
                "required": {
                    "unet_name": [
                        [
                            "minimax-h3/remote_stale.safetensors",
                            "other/minimax_h3_wrong_folder.safetensors",
                        ],
                        {},
                    ]
                }
            }
        }
    }
    state.object_info["BasicScheduler"] = {
        "BasicScheduler": {"input": {"required": {"scheduler": [["beta57"], {}]}}}
    }
    state.object_info["KSamplerSelect"] = {
        "KSamplerSelect": {"input": {"required": {"sampler_name": [["euler"], {}]}}}
    }
    models = tmp_path / "diffusion_models"
    h3 = models / "minimax-h3"
    h3.mkdir(parents=True)
    (h3 / "local_current.safetensors").write_bytes(b"")

    catalog = build_catalog(
        Settings(
            data_dir=tmp_path / "data",
            models_dir=models,
            comfy_input_dir=tmp_path / "input",
            comfy_url=url,
        )
    )

    assert catalog.diffusion_models_source == "disk"
    assert catalog.diffusion_models == ["minimax-h3/local_current.safetensors"]
    assert catalog.default_diffusion_model == "minimax-h3/local_current.safetensors"


def test_the_catalog_prefers_the_live_lists_and_scans_input_media(comfy, tmp_path: Path):
    state, url = comfy
    state.object_info["BasicScheduler"] = {
        "BasicScheduler": {"input": {"required": {"scheduler": [["beta57", "karras"], {}]}}}
    }
    state.object_info["KSamplerSelect"] = {
        "KSamplerSelect": {
            "input": {"required": {"sampler_name": ["COMBO", {"options": ["euler"]}]}}
        }
    }
    state.object_info["ResolutionSelector"] = {
        "ResolutionSelector": {
            "input": {"required": {"aspect_ratio": ["COMBO", {"options": ["16:9 (Widescreen)"]}]}}
        }
    }
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "shot.png").write_bytes(b"")
    (input_dir / "clip.mp4").write_bytes(b"")
    (input_dir / "voice.wav").write_bytes(b"")
    (input_dir / "readme.md").write_bytes(b"")

    settings = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=input_dir,
        comfy_url=url,
    )
    catalog = build_catalog(settings)
    assert catalog.comfy_online is True
    assert catalog.source == "comfy"
    assert catalog.schedulers == ["beta57", "karras"]
    assert catalog.samplers == ["euler"]
    assert catalog.images == ["shot.png"]
    assert catalog.videos == ["clip.mp4"]
    assert catalog.audios == ["voice.wav"]
    assert catalog.defaults["first_frame"] == "shot.png"
    assert catalog.defaults["mode"] == "flf2v"


def test_the_catalog_defaults_to_text_mode_with_no_input_images(comfy, tmp_path: Path):
    _state, url = comfy
    settings = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=tmp_path / "empty",
        comfy_url=url,
    )
    (tmp_path / "empty").mkdir()
    catalog = build_catalog(settings)
    assert catalog.defaults["mode"] == "t2v"
    assert catalog.defaults["first_frame"] == ""
    assert catalog.default_first_frame == ""
    assert catalog.default_ref_images == []


def _catalog_over(tmp_path: Path, names: Iterable[str]) -> Catalog:
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    for name in names:
        (input_dir / name).write_bytes(b"")
    return build_catalog(
        Settings(
            data_dir=tmp_path / "data",
            models_dir=tmp_path / "models",
            comfy_input_dir=input_dir,
            comfy_url="http://127.0.0.1:1",
        )
    )


def test_the_baseline_frame_wins_over_whatever_sorts_first(tmp_path: Path):
    """Alphabetical order picked an arbitrary still, so every new run started with a chore."""
    catalog = _catalog_over(tmp_path, ["aaa-first-alphabetically.png", BASELINE_FIRST_FRAME])
    assert catalog.default_first_frame == BASELINE_FIRST_FRAME
    assert catalog.defaults["first_frame"] == BASELINE_FIRST_FRAME


def test_a_missing_baseline_frame_falls_back_to_something_that_exists(tmp_path: Path):
    catalog = _catalog_over(tmp_path, ["only-thing-here.png"])
    assert catalog.default_first_frame == "only-thing-here.png"


def test_the_baseline_references_come_back_in_their_own_order(tmp_path: Path):
    """They read as one scene, so the order they were authored in is the order to offer."""
    catalog = _catalog_over(tmp_path, sorted(BASELINE_REF_IMAGES, reverse=True))
    assert catalog.default_ref_images == list(BASELINE_REF_IMAGES)


def test_an_incomplete_baseline_reference_set_offers_nothing(tmp_path: Path):
    """Half a reference set is not a lighter version of it, it is a different subject.

    An arbitrary stand-in would be worse: references define what is generated, so a wrong
    one produces a confidently wrong video rather than an obvious blank.
    """
    catalog = _catalog_over(tmp_path, [BASELINE_REF_IMAGES[0], "unrelated.png"])
    assert catalog.default_ref_images == []


# --- turbo LoRAs -----------------------------------------------------------


def test_the_lora_list_comes_from_the_node_that_will_load_it(comfy, tmp_path: Path):
    """The installed node's own combo is the only list that cannot disagree with the run."""
    state, url = comfy
    state.object_info["MiniMaxH3TurboLoRA"] = {
        "MiniMaxH3TurboLoRA": {
            "input": {
                "required": {
                    "lora_name": [
                        "COMBO",
                        {
                            "options": [
                                "MiniMax-H3-Turbo-LoRA-4steps.safetensors",
                                "MiniMax-H3-Turbo-LoRA-8steps.safetensors",
                                "wan22_lightx2v.safetensors",
                            ]
                        },
                    ]
                }
            }
        }
    }
    settings = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=tmp_path / "input",
        comfy_url=url,
    )
    catalog = build_catalog(settings)

    assert catalog.turbo_loras_source == "comfy"
    assert catalog.turbo_loras == [
        "MiniMax-H3-Turbo-LoRA-4steps.safetensors",
        "MiniMax-H3-Turbo-LoRA-8steps.safetensors",
    ]
    assert catalog.default_turbo_lora == "MiniMax-H3-Turbo-LoRA-4steps.safetensors"
    assert catalog.defaults["turbo_lora"] == catalog.default_turbo_lora
    assert catalog.defaults["turbo_lora_strength"] == DEFAULT_TURBO_STRENGTH
    # The form should not have to parse a filename to say what a run will sample at.
    assert catalog.turbo_lora_steps == {
        "MiniMax-H3-Turbo-LoRA-4steps.safetensors": 4,
        "MiniMax-H3-Turbo-LoRA-8steps.safetensors": 8,
    }


def test_an_offline_comfy_still_offers_the_loras_on_disk(tmp_path: Path):
    loras = tmp_path / "loras"
    loras.mkdir()
    for name in ("minimax_h3_turbo_6step.safetensors", "some_other_lora.safetensors"):
        (loras / name).write_bytes(b"")

    settings = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models" / "diffusion_models",
        loras_dir=loras,
        comfy_input_dir=tmp_path / "input",
        comfy_url="http://127.0.0.1:9",
    )
    catalog = build_catalog(settings)

    assert catalog.turbo_loras_source == "disk"
    assert catalog.turbo_loras == ["minimax_h3_turbo_6step.safetensors"]
    assert catalog.default_turbo_lora == "minimax_h3_turbo_6step.safetensors"


def test_with_nothing_to_read_the_picker_still_names_the_shipped_lora(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        comfy_input_dir=tmp_path / "input",
        comfy_url="http://127.0.0.1:9",
    )
    catalog = build_catalog(settings)

    assert catalog.turbo_loras_source == "fallback"
    assert catalog.turbo_loras == [DEFAULT_TURBO_LORA]
    assert catalog.default_turbo_lora == DEFAULT_TURBO_LORA
