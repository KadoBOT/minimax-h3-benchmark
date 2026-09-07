"""Bind API scene inputs to the saved, editable H3 workflows."""

import json
from pathlib import Path

from .editor import to_prompt


ROOT = Path(__file__).parent
PRESETS = {"speed": "Speed", "quality": "Quality", "quality_pece": "Quality PECE", "motion": "Motion / De-rope"}
WORKFLOW_FILES = {
    "quality": "minimax_h3_clean.json",
    "speed": "h3_presets/speed.json",
    "quality_pece": "h3_presets/quality_pece.json",
    "motion": "h3_presets/motion.json",
}
DEFAULTS = {
    "preset": "quality", "prompt": "", "seed": 42, "width": 1344, "height": 768, "frames": 175,
    "ref_image_size": "match",
    "references": {"images": [], "videos": [], "video_audios": [], "audios": []},
    "guides": [], "first_frame": "", "last_frame": "",
    "filename_prefix": "MiniMax-H3/clean", "final_audio": "",
}


def normalize(inputs):
    unknown = inputs.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError("Unknown H3 inputs: " + ", ".join(sorted(unknown)))
    values = {**DEFAULTS, **inputs}
    if values["preset"] not in PRESETS:
        raise ValueError("preset must be speed, quality, quality_pece, or motion")
    for field in ("references", "guides"):
        if isinstance(values[field], str):
            values[field] = json.loads(values[field])
    refs = values["references"]
    if not isinstance(refs, dict) or refs.keys() - DEFAULTS["references"].keys():
        raise ValueError("references must contain images, videos, video_audios, or audios")
    values["references"] = {key: refs.get(key, []) for key in DEFAULTS["references"]}
    for key, files in values["references"].items():
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ValueError(f"references.{key} must be a list of uploaded filenames")
    if not isinstance(values["guides"], list):
        raise ValueError("guides must be a list of timed image, video, or audio guides")
    if not isinstance(values["seed"], int) or not 0 <= values["seed"] <= 2**53 - 1:
        raise ValueError("seed must be an integer from 0 through 2^53-1")
    for key in ("width", "height", "frames"):
        if not isinstance(values[key], int) or isinstance(values[key], bool) or values[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if values["ref_image_size"] not in ("match", "max"):
        raise ValueError("ref_image_size must be match or max")
    return values, {"width": values["width"], "height": values["height"], "frames": values["frames"], "fps": 24}


def build(inputs, validate_file=lambda name: name, resolve_model=lambda category, name: name,
          *, workflow_dir, node_info):
    values, dimensions = normalize(inputs)
    workflow = json.loads((Path(workflow_dir) / WORKFLOW_FILES[values["preset"]]).read_text(encoding="utf-8"))
    graph = to_prompt(workflow, node_info)
    roles = {}
    for node_id, node in graph.items():
        role = node.get("_meta", {}).get("h3_role")
        if role:
            if role in roles:
                raise ValueError(f"Duplicate H3 API role: {role}")
            roles[role] = node_id
        args = node["inputs"]
        for field, category in (("unet_name", "diffusion_models"), ("vae_name", "vae"),
                                ("clip_name", "text_encoders"), ("lora_name", "loras")):
            if field in args and isinstance(args[field], str):
                args[field] = resolve_model(category, args[field])
    for node in workflow["nodes"]:
        node_id = str(node["id"])
        if node_id not in graph:
            continue
        properties = node.get("properties", {})
        for field, request_key in properties.get("h3_inputs", {}).items():
            value = values[request_key]
            if request_key == "seed":
                value = (value + properties.get("h3_seed_offset", 0)) % 2**53
            graph[node_id]["inputs"][field] = value
    for role in ("conditioning", "guider", "video_vae", "audio_vae", "output_video"):
        if role not in roles:
            raise ValueError(f"The saved workflow is missing the H3 API role: {role}")
    conditioning = graph[roles["conditioning"]]["inputs"]
    conditioners = [conditioning]
    if "motion_conditioning" in roles:
        conditioners.append(graph[roles["motion_conditioning"]]["inputs"])
    next_id = max(int(node["id"]) for node in workflow["nodes"]) + 1

    def add(kind, **args):
        nonlocal next_id
        key = str(next_id)
        next_id += 1
        graph[key] = {"class_type": kind, "inputs": args}
        return [key, 0]

    def image(name):
        return add("LoadImage", image=validate_file(name))

    def audio(name):
        return add("LoadAudio", audio=validate_file(name))

    def video(name):
        components = add("GetVideoComponents", video=add("LoadVideo", file=validate_file(name)))
        return add("H3ReferenceFrames", images=components, fps=[components[0], 2])

    refs = values["references"]
    for target in conditioners:
        for key in list(target):
            if key.startswith(("ref_images.", "ref_videos.", "ref_video_audios.", "ref_audios.")):
                del target[key]
    for group, prefix, loader in (("images", "ref_image_", image), ("videos", "ref_video_", video),
                                  ("video_audios", "ref_video_audio_", audio), ("audios", "ref_audio_", audio)):
        for i, name in enumerate(refs[group]):
            if name:
                link = loader(name)
                for target in conditioners:
                    target[f"ref_{group}.{prefix}{i}"] = link

    guides = list(values["guides"])
    if values["first_frame"]:
        guides.insert(0, {"image": values["first_frame"], "frame": 0})
    if values["last_frame"]:
        guides.append({"image": values["last_frame"], "frame": -1})
    guider = graph[roles["guider"]]["inputs"]
    positive = guider["conditioning"]
    for guide in guides:
        if not isinstance(guide, dict) or guide.keys() - {"image", "video", "audio", "time", "frame"}:
            raise ValueError("A guide accepts image/video/audio filenames and time or frame")
        if guide.get("image") and guide.get("video"):
            raise ValueError("Use image or video per guide, not both")
        args = {"positive": positive, "latent": [roles["conditioning"], 1],
                "vae": [roles["video_vae"], 0], "audio_vae": [roles["audio_vae"], 0],
                "frame_idx": int(guide["frame"]) if "frame" in guide else round(float(guide.get("time", 0)) * 24)}
        if guide.get("image"):
            args["image"] = image(guide["image"])
        if guide.get("video"):
            args["image"] = video(guide["video"])
        if guide.get("audio"):
            args["audio"] = audio(guide["audio"])
        if "image" not in args and "audio" not in args:
            raise ValueError("A guide needs an image, video, or audio")
        positive = add("MiniMaxH3AddGuide", **args)
    guider["conditioning"] = positive
    if values["final_audio"]:
        graph[roles["output_video"]]["inputs"]["audio"] = audio(values["final_audio"])
    return {"contract_version": 1, "workflow": graph, "editor_workflow": workflow,
            "inputs": values, "dimensions": dimensions}
