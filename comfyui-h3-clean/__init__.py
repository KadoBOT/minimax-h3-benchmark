import os

from aiohttp import web
import folder_paths
import nodes
from comfy_api.internal import _ComfyNodeInternal
from server import PromptServer

from .workflow import DEFAULTS, PRESETS, WORKFLOW_FILES, build


def input_file(name):
    root = os.path.realpath(folder_paths.get_input_directory())
    path = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, path]) != root or not os.path.isfile(path):
        raise ValueError(f"Missing or invalid uploaded file: {name}")
    return name


def model_file(category, name):
    files = folder_paths.get_filename_list(category)
    if name in files:
        return name
    leaf = name.replace("\\", "/").rsplit("/", 1)[-1]
    matches = [f for f in files if f.replace("\\", "/").rsplit("/", 1)[-1] == leaf]
    if len(matches) != 1:
        raise ValueError(f"Expected one installed {category} model named {leaf}; found {len(matches)}")
    return matches[0]


class H3ReferenceFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "fps": ("FLOAT", {"default": 24, "min": 0.01})}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "resample"
    CATEGORY = "video/MiniMax H3"

    def resample(self, images, fps):
        if fps == 24:
            return (images,)
        indices = [min(len(images) - 1, round(i * fps / 24)) for i in range(max(1, round(len(images) * 24 / fps)))]
        return (images[indices],)


NODE_CLASS_MAPPINGS = {"H3ReferenceFrames": H3ReferenceFrames}


def node_info(name):
    cls = nodes.NODE_CLASS_MAPPINGS[name]
    if issubclass(cls, _ComfyNodeInternal):
        return cls.GET_NODE_INFO_V1()
    return {"input": cls.INPUT_TYPES()}


@PromptServer.instance.routes.get("/h3_clean/v1/manifest")
async def manifest(request):
    return web.json_response({
        "contract_version": 1, "component_version": "2.0.0", "workflow_name": "minimax_h3_clean.json",
        "prepare_url": "/h3_clean/v1/prepare", "defaults": DEFAULTS,
        "workflow_files": WORKFLOW_FILES,
        "presets": [{"id": key, "name": label} for key, label in PRESETS.items()],
        "capabilities": {"references": True, "guides": True, "native_audio": True},
        "template_catalog": {"version": 2, "managed_keys": ["preset"],
            "categories": [{"id": "h3", "name": "MiniMax H3"}],
            "templates": [{"id": key, "name": label, "category": "h3", "description": "Fast action or visible smearing; Quality plus De-rope, original audio preserved" if key == "motion" else label,
                           "evidence": "measured", "tradeoff": "Fast preview" if key == "speed" else "Quality plus three-step De-rope; longer runtime" if key == "motion" else "Reviewed two-pass finish",
                           "values": {"preset": key}, "requirements": [], "tags": ["test" if key == "speed" else "production"]}
                          for key, label in PRESETS.items()]},
    })


@PromptServer.instance.routes.post("/h3_clean/v1/prepare")
async def prepare(request):
    try:
        payload = await request.json()
        if payload.get("contract_version") != 1:
            raise ValueError("Expected contract_version 1")
        result = build(payload["inputs"], input_file, model_file,
                       workflow_dir=os.path.join(folder_paths.get_user_directory(), "default", "workflows"),
                       node_info=node_info)
        return web.json_response(result)
    except (ValueError, KeyError, TypeError) as error:
        return web.json_response({"error": {"code": "invalid_inputs", "message": str(error)}}, status=400)
