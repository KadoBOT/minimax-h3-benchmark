"""Node ids and widget orders for the MiniMax H3 workflow templates.

The ids come from the workflow JSON files in the repository root. Grouping them by role
means the prompt builder reads as intent rather than as a wall of magic numbers.
"""

from __future__ import annotations

from typing import Final

# --- loaders and encoders --------------------------------------------------
UNET: Final = 1
CLIP: Final = 2
VAE_VIDEO: Final = 3
VAE_AUDIO: Final = 4
GGUF_UNET: Final = 130
GGUF_CLIP: Final = 131
INT8_UNET: Final = 124

# --- conditioning ----------------------------------------------------------
CONDITIONING: Final = 5  # MiniMaxH3ImageToVideo or MiniMaxH3ReferenceToVideo
PROMPT: Final = 107
RESOLUTION: Final = 98
DURATION: Final = 102
FRAME_MATH: Final = 103

# --- sampling --------------------------------------------------------------
SCHEDULER: Final = 6
SAMPLER_SELECT: Final = 7
GUIDER: Final = 8
SAMPLER: Final = 10
SEED: Final = 118
NOISE: Final = 119
SIGMA_SHIFT: Final = 123

# --- model patches ---------------------------------------------------------
SAGE_ATTN: Final = 91
SOL_ATTN: Final = 92
TURBO_LORA: Final = 155
OPTIONAL_LORA: Final = 148

# --- caches ----------------------------------------------------------------
EASY_CACHE: Final = 15
SPECTRUM: Final = 122
H3_CACHE: Final = 128

# --- media inputs ----------------------------------------------------------
LOAD_FIRST_FRAME: Final = 20
LOAD_LAST_FRAME: Final = 145
FIT_FIRST: Final = 146
FIT_LAST: Final = 147

REF_IMAGE_BASE: Final = 200  # 200–208, nine LoadImage nodes
REF_VIDEO_BASE: Final = 210  # 210–212, three LoadVideo nodes
REF_VIDEO_COMPONENTS_BASE: Final = 220  # 220–222, GetVideoComponents per video
REF_AUDIO_BASE: Final = 230  # 230–232, three standalone LoadAudio nodes
# Soundtrack overrides live at 240+ so they can never collide with the standalone
# LoadAudio nodes at 230+.
REF_VIDEO_AUDIO_BASE: Final = 240

# --- post-processing and output -------------------------------------------
VAE_DECODE: Final = 125
VAE_DECODE_AUDIO: Final = 12
CLEAN_VRAM: Final = 97
CLEAN_TEXT_ENCODER: Final = 144
RIFE: Final = 96
INTERP_FPS: Final = 95
UPSCALER: Final = 111
BASE_FPS: Final = 108
VIDEO_COMBINE: Final = 110

# --- nodes that exist only to drive the ComfyUI editor --------------------
# Switches and step plumbing are resolved offline, so they never reach the API prompt.
QUANT_SWITCH: Final = 126
CACHE_SWITCH: Final = 127
CLIP_SWITCH: Final = 140
MODEL_SWITCH: Final = 142
ATTN_SWITCH: Final = 163
STEPS_SWITCH: Final = 158
FPS_SWITCH: Final = 109
TURBO_STEPS: Final = 157
DEFAULT_STEPS: Final = 159
FLOAT_TO_INT: Final = 161
CACHE_BYPASSER: Final = 139
TRANSFORMER_BYPASSER: Final = 143

# Optional editor exports. Their links break once the video path is rewired, and ComfyUI
# validates them as graph roots if they are left in the prompt.
SECONDARY_COMBINE: Final = 150
IMAGE_FROM_BATCH: Final = 152
SAVE_AUDIO: Final = 149
LAST_FRAME_INDEX: Final = 151
SAVE_LAST_FRAME: Final = 153

EDITOR_ONLY_NODES: Final[tuple[int, ...]] = (
    QUANT_SWITCH,
    CACHE_SWITCH,
    CLIP_SWITCH,
    MODEL_SWITCH,
    ATTN_SWITCH,
    STEPS_SWITCH,
    FPS_SWITCH,
    TURBO_STEPS,
    DEFAULT_STEPS,
    FLOAT_TO_INT,
    SECONDARY_COMBINE,
    IMAGE_FROM_BATCH,
    SAVE_AUDIO,
    LAST_FRAME_INDEX,
    SAVE_LAST_FRAME,
)

CACHE_NODES: Final[tuple[int, ...]] = (EASY_CACHE, SPECTRUM, H3_CACHE)

CACHE_NODE_BY_NAME: Final[dict[str, int]] = {
    "easy": EASY_CACHE,
    "spectrum": SPECTRUM,
    "h3": H3_CACHE,
}

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

# Widget order matching each node's `widgets_values` array. Editor-only trailing entries
# (control_after_generate, seed_mode) are deliberately absent.
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
    "LoadImage": ["image"],
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
        "verbose",
        "use_tma",
    ],
    "MiniMaxH3TurboLoRA": ["lora_name", "strength_model"],
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
    "RTXVideoSuperResolution": ["resize_type", "scale", "quality"],
    "VHS_VideoCombine": None,  # dict-shaped widgets_values, handled separately
    "Any Switch (rgthree)": [],
    "BasicGuider": [],
    "SamplerCustomAdvanced": [],
    "VAEDecode": [],
    "VAEDecodeAudio": [],
    "easy cleanGpuUsed": [],
}
