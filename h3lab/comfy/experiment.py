"""Apply only explicit benchmark overrides to a saved workflow."""

from copy import deepcopy
from typing import Any


def node_roles(graph: dict) -> dict[str, str]:
    return {node["_meta"]["h3_role"]: node_id for node_id, node in graph.items()
            if node.get("_meta", {}).get("h3_role")}


def experiment_fields(graph: dict) -> dict[str, tuple[str, str]]:
    roles = node_roles(graph)
    targets = {
        "diffusion_model": ("model_loader", "unet_name"),
        "weight_dtype": ("model_loader", "weight_dtype"),
        "video_vae": ("video_vae", "vae_name"),
        "audio_vae": ("audio_vae", "vae_name"),
        "text_encoder": ("text_encoder", "clip_name"),
        "scheduler": ("schedule", "scheduler"),
        "steps": ("schedule", "steps"),
        "denoise": ("schedule", "denoise"),
        "shift_video": ("sampling", "shift_video"),
        "shift_audio": ("sampling", "shift_audio"),
        "ffn_chunks": ("ffn", "chunks"),
        "bridge_alpha": ("bridge", "alpha"),
        "refine_sigmas": ("refine_sigmas", "sigmas"),
    }
    fields = {key: (roles.get(role, ""), field) for key, (role, field) in targets.items()}
    sampler = graph.get(roles.get("sampler"), {}).get("inputs", {}).get("sampler")
    fields["sampler"] = (sampler[0] if sampler else "", "sampler_name")
    return fields


def apply_experiment(prompt: dict, experiment: dict[str, Any]) -> dict:
    graph = deepcopy(prompt)
    roles = node_roles(graph)
    fields = experiment_fields(graph)
    unknown = experiment.keys() - fields.keys() - {"loras", "node_inputs", "refine_enabled", "refine_sampler"}
    if unknown:
        raise ValueError("Unknown experiment fields: " + ", ".join(sorted(unknown)))
    primary = roles.get("sampler")
    refine = roles.get("refine")
    if experiment.get("refine_enabled") and not refine:
        graph["benchmark_refine_sigmas"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": "0.15,0.075,0"},
                                             "_meta": {"h3_role": "refine_sigmas"}}
        refine = "benchmark_refine"
        graph[refine] = deepcopy(graph[primary])
        graph[refine]["_meta"] = {"h3_role": "refine"}
        graph[refine]["inputs"].update(sigmas=["benchmark_refine_sigmas", 0], latent_image=[primary, 0])
        graph[roles["decode"]]["inputs"]["samples"] = [refine, 0]
        fields = experiment_fields(graph)
    if "sampler" in experiment:
        graph["benchmark_primary_sampler"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": experiment["sampler"]}}
        graph[primary]["inputs"]["sampler"] = ["benchmark_primary_sampler", 0]
    for key, (node_id, field) in fields.items():
        if key in experiment and key != "sampler":
            if node_id not in graph:
                raise ValueError(f"The saved workflow has no node for {key}")
            graph[node_id]["inputs"][field] = experiment[key]
    if "refine_sampler" in experiment:
        if not refine:
            raise ValueError("Enable refinement before changing its sampler")
        graph["benchmark_refine_sampler"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": experiment["refine_sampler"]}}
        graph[refine]["inputs"]["sampler"] = ["benchmark_refine_sampler", 0]
    if experiment.get("refine_enabled") is False and refine:
        for node in graph.values():
            for field, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and value[0] == refine:
                    node["inputs"][field] = [primary, value[1]]
        del graph[refine]
        for unused in (roles.get("refine_sigmas"), "benchmark_refine_sampler"):
            if unused and not any(isinstance(v, list) and len(v) == 2 and v[0] == unused
                                  for node in graph.values() for v in node["inputs"].values()):
                graph.pop(unused, None)
    if str(experiment.get("diffusion_model", "")).lower().endswith(".gguf"):
        graph[roles["model_loader"]]["class_type"] = "UnetLoaderGGUF"
        graph[roles["model_loader"]]["inputs"].pop("weight_dtype", None)
    if "loras" in experiment:
        entry = graph[roles["ffn"]]["inputs"]
        model = entry["model"]
        for index, lora in enumerate(experiment["loras"]):
            node_id = f"benchmark_lora_{index}"
            graph[node_id] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": model, "lora_name": lora["name"], "strength_model": lora.get("strength", 1.0),
            }}
            model = [node_id, 0]
        entry["model"] = model
    for node_id, inputs in experiment.get("node_inputs", {}).items():
        if node_id not in graph:
            raise ValueError(f"Unknown experiment node {node_id}")
        graph[node_id]["inputs"].update(inputs)
    return graph
