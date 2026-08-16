"""What the lab knows about node *classes*, as opposed to any one workflow.

Everything here is keyed by class type, never by node id. Ids are an accident of how a
workflow was last edited — `roles.py` works out which node does what, and the ids it falls
back on live there, with the rules that use them.

The widget order table is a fallback. A node saved by a recent editor declares its own order,
and a running ComfyUI knows the installed one; both outrank this file. It answers for nodes
that declare nothing and for hand-written graphs in tests.
"""

from __future__ import annotations

from typing import Final

# Node types that only exist in the editor graph and have no executable class.
UI_ONLY_TYPES: Final[frozenset[str]] = frozenset(
    {
        "Note",
        "MarkdownNote",
        "Fast Groups Bypasser (rgthree)",
        "Fast Bypasser (rgthree)",
        "Reroute",
    }
)

# The commentary an export keeps. The rest of `UI_ONLY_TYPES` is resolved switchgear: an
# rgthree bypasser drives nodes by group membership, and in an export the groups it drove no
# longer all exist, so it would offer to toggle nothing.
UI_KEPT_TYPES: Final[frozenset[str]] = frozenset({"Note", "MarkdownNote"})

# Output slots of the loaders `apply_config` mints when the template bypassed them. Only the
# editor projection needs these: an API prompt names its source node and slot index, while a
# node in the editor has to declare the slots those indices refer to.
OUTPUT_SLOTS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "LoadImage": (("IMAGE", "IMAGE"), ("MASK", "MASK")),
    "LoadVideo": (("VIDEO", "VIDEO"),),
    "LoadAudio": (("AUDIO", "AUDIO"),),
    "GetVideoComponents": (
        ("images", "IMAGE"),
        ("audio", "AUDIO"),
        ("fps", "FLOAT"),
        ("bit_depth", "INT"),
    ),
}

# Widget order matching each node's `widgets_values` array. Editor-only trailing entries
# (control_after_generate, seed_mode) are deliberately absent. Refresh it against the
# installed ComfyUI with `h3lab check --widgets`.
WIDGET_ORDER: Final[dict[str, list[str] | None]] = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "OTUNetLoaderW8A8": [
        "unet_name",
        "weight_dtype",
        "model_type",
        "on_the_fly_quantization",
        "enable_convrot",
        "lora_mode",
    ],
    "GGUFLoaderKJ": [
        "model_name",
        "extra_model_name",
        "dequant_dtype",
        "patch_dtype",
        "patch_on_device",
        "enable_fp16_accumulation",
        "attention_override",
    ],
    "CLIPLoader": ["clip_name", "type", "device"],
    "CLIPLoaderGGUF": ["clip_name", "type"],
    "VAELoader": ["vae_name"],
    "LoadImage": ["image", "upload"],
    "LoadVideo": ["file"],
    "LoadAudio": ["audio"],
    "GetVideoComponents": [],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "KSamplerSelect": ["sampler_name"],
    "EasyCache": ["reuse_threshold", "start_percent", "end_percent", "verbose"],
    "SpectrumApplyMiniMaxH3": [
        "enabled",
        "blend_weight",
        "degree",
        "ridge_lambda",
        "window_size",
        "flex_window",
        "warmup_steps",
        "tail_actual_steps",
        "max_history",
        "debug",
        "history_storage",
        "bootstrap_first_forecast",
        "anchor_residual_feedback",
        "selective_rollback_correction",
        "offline_smoothing_replay",
        "audio_blend_weight",
    ],
    "UC_MiniMaxH3Cache": [
        "reuse_threshold",
        "start_percent",
        "end_percent",
        "max_steps",
        "device",
        "verbose",
    ],
    "SolAttnPatch": [
        "tau",
        "start_percent",
        "end_percent",
        "min_tokens",
        "int8_qk",
        "sink_conditioning",
        "morton",
        "morton_curve",
        "int8_pv",
        "verbose",
        "use_tma",
        "dense_blocks",
        "tau_profile",
    ],
    "MiniMaxH3TurboLoRA": ["lora_name", "strength", "low_vram"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "ImageScale": ["upscale_method", "width", "height", "crop"],
    "CM_FloatToInt": ["a"],
    "ResolutionSelector": ["aspect_ratio", "megapixels", "multiple"],
    "PrimitiveFloat": ["value"],
    "PrimitiveStringMultiline": ["value"],
    "easy seed": ["seed"],
    "RandomNoise": ["noise_seed"],
    "PathchSageAttentionKJ": ["sage_attention", "allow_compile"],
    "MiniMaxH3SigmaShift": ["shift_video", "shift_audio"],
    "MiniMaxH3Studio": [
        "mode",
        "prompt",
        "duration",
        "aspect_ratio",
        "megapixels",
        "ref_image_size",
        "first_frame",
        "last_frame",
        "references",
        "guides",
        "steps",
        "turbo",
        "turbo_lora",
        "scheduler",
        "sampler_name",
        "cache",
        "upscale_ltx",
        "upscale_rtx",
        "seed_mode",
        "seed",
        "interpolation",
        "clean_vram",
        "sol_attn",
        "post_grade",
        "dual",
        "shift_video",
        "pass2_steps",
        "pass2_denoise",
        "pass2_scheduler",
        "pass2_sampler_name",
        "pass2_shift",
        "pass2_scale",
        "h3s_ui",
    ],
    "MiniMaxH3ImageToVideo": ["prompt", "width", "height", "length"],
    "MiniMaxH3ReferenceToVideo": ["prompt", "width", "height", "length", "ref_image_size"],
    "ComfyMathExpression": ["expression"],
    "RIFEInterpolation": [
        "source_fps",
        "target_fps",
        "scale",
        "model_name",
        "batch_size",
        "use_fp16",
    ],
    "FrameInterpolationModelLoader": ["model_name"],
    "FrameInterpolate": ["multiplier"],
    # A dynamic combo: the chosen mode decides whether the following widgets are
    # `resize_type.scale` or `resize_type.width` + `resize_type.height`. Only the saved node
    # knows, which is why what a node declares outranks this table.
    "RTXVideoSuperResolution": ["resize_type", "quality"],
    "VHS_VideoCombine": None,  # dict-shaped widgets_values, handled separately
    "Seed (rgthree)": ["seed"],
    "SaveImage": ["filename_prefix"],
    "SaveAudio": ["filename_prefix"],
    "ImageFromBatch": ["batch_index", "length"],
    "Any Switch (rgthree)": [],
    "BasicGuider": [],
    "SamplerCustomAdvanced": [],
    "VAEDecode": [],
    "VAEDecodeAudio": [],
    "easy cleanGpuUsed": [],
    "MiniMaxH3MemoryEfficientSageAttentionPatch": [],
}
