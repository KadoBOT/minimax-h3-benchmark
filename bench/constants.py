from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "updated_h3_wf.json"
RESULTS_DIR = ROOT / "results"
BENCHMARK_JSON = RESULTS_DIR / "benchmark.json"
VIDEOS_DIR = RESULTS_DIR / "videos"
RUNS_DIR = RESULTS_DIR / "runs"
UI_DIR = ROOT / "ui"
SUITE_LOG = RESULTS_DIR / "suite.log"

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_UI_PORT = 8787

# ComfyUI diffusion_models folder (filenames only are sent to loaders)
DIFFUSION_MODELS_DIR = Path(r"E:\AI\Models\diffusion_models")

MODE_ACTIVE = 0
MODE_BYPASS = 4

# --- v3 node IDs ---
NODE_UNET = 1
NODE_CLIP = 2
NODE_VAE_VIDEO = 3
NODE_VAE_AUDIO = 4
NODE_I2V = 5
NODE_SCHEDULER = 6
NODE_SAMPLER = 7
NODE_GUIDER = 8
NODE_SAMPLER_ADV = 10
NODE_VAE_DECODE_AUDIO = 12
NODE_EASYCACHE = 15
NODE_LOAD_IMAGE = 20
NODE_SAGE = 91
NODE_SOL_ATTN = 92
NODE_RIFE = 96
NODE_CLEAN_VRAM = 97
NODE_RESOLUTION = 98
NODE_DURATION = 102
NODE_FRAME_MATH = 103
NODE_PROMPT = 107
NODE_BASE_FPS = 108
NODE_FPS_SWITCH = 109
NODE_VIDEO_COMBINE = 110
NODE_UPSCALER = 111
NODE_SEED = 118
NODE_NOISE = 119
NODE_SPECTRUM = 122
NODE_SIGMA_SHIFT = 123
NODE_INT8 = 124
NODE_VAE_DECODE = 125
NODE_H3_CACHE = 128
NODE_GGUF = 130
NODE_CLIP_GGUF = 131
NODE_CACHE_BYPASSER = 139
NODE_CLIP_SWITCH = 140
NODE_MODEL_SWITCH = 142
NODE_TRANSFORMER_BYPASSER = 143
NODE_CLEAN_TE = 144
NODE_LAST_FRAME = 145
NODE_FIT_FIRST = 146
NODE_FIT_LAST = 147
NODE_OPTIONAL_LORA = 148
NODE_TURBO_LORA = 155
NODE_TURBO_STEPS = 157
NODE_STEPS_SWITCH = 158
NODE_DEFAULT_STEPS = 159
NODE_FLOAT_TO_INT = 161
NODE_ATTN_SWITCH = 163
NODE_INTERP_FPS = 95
NODE_TARGET_FPS = 95

# v2 switch nodes removed in v3 graph; kept so existing modules still import
NODE_SWITCH_QUANT = 126
NODE_SWITCH_CACHE = 127

FIXED_SEED = 42

# ComfyUI input folder + default first-frame image (FL2V)
COMFY_INPUT_DIR = Path(r"C:\Users\ricar\Documents\ComfyUI\ComfyUI\input")
DEFAULT_FIRST_FRAME = "Cyberpunk_courier_riding_magneti…_2K_202608070843.jpeg"
DEFAULT_FIRST_FRAME_PATH = COMFY_INPUT_DIR / DEFAULT_FIRST_FRAME

NVFP4_UNET = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
INT8_UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
GGUF_UNET = "MiniMax-H3-FL2VA-Q4_K_M.gguf"
GGUF_CLIP = "qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf"

BASELINE_PROMPT = (
    "[0s-1.5s] Low tracking shot races forward with the courier as he accelerates hard on the magnetic skateboard, cyan board thrusters flare brighter, rain streaks turn into diagonal streaks across the lens, neon signs smear into long light trails while the alley walls rush past on both sides.\n"  
    "[1.5s-3.5s] He snaps into a sharp left bank at full speed, the board sprays a sheet of water and sparks off the wet pavement, a swarm of holographic ads and floating drones whip past his head, camera whip-pans to keep him centered as background traffic blurs into pure light streaks.\n"
    "[3.5s-5s] The courier launches off a sudden ramp of debris, body and board launching airborne in a tight arc through heavy rain and neon haze, camera follows the upward trajectory then drops with him as he lands hard, water exploding outward in all directions while the alley continues to rush past at extreme speed."
)

FALLBACK_SCHEDULERS = ["beta", "beta57", "simple"]
FALLBACK_SAMPLERS = ["euler", "res_multistep", "er_sde"]

DEFAULT_SCHEDULER = "beta57"
DEFAULT_SAMPLER = "euler"
DEFAULT_ASPECT_RATIO = "16:9 (Widescreen)"

FALLBACK_ASPECT_RATIOS = [
    "1:1 (Square)",
    "2:3 (Portrait Photo)",
    "3:2 (Photo)",
    "3:4 (Portrait Standard)",
    "4:3 (Standard)",
    "9:16 (Portrait Widescreen)",
    "16:9 (Widescreen)",
    "21:9 (Ultrawide)",
]
