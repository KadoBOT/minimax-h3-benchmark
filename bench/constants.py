from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "minimax-h3_test.i2v.v2.workflow.json"
RESULTS_DIR = ROOT / "results"
BENCHMARK_JSON = RESULTS_DIR / "benchmark.json"
VIDEOS_DIR = RESULTS_DIR / "videos"
RUNS_DIR = RESULTS_DIR / "runs"
UI_DIR = ROOT / "ui"
SUITE_LOG = RESULTS_DIR / "suite.log"

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_UI_PORT = 8787

# ComfyUI node mode
MODE_ACTIVE = 0
MODE_BYPASS = 4

# Node IDs from minimax-h3_test.i2v.v2.workflow.json
NODE_UNET = 1
NODE_CLIP = 2
NODE_VAE_VIDEO = 3
NODE_VAE_AUDIO = 4
NODE_I2V = 5
NODE_SCHEDULER = 6
NODE_SAMPLER = 7
NODE_GUIDER = 8
NODE_SAMPLER_ADV = 10
NODE_EASYCACHE = 15
NODE_LOAD_IMAGE = 20
NODE_SAGE = 91
NODE_SOL_ATTN = 92
NODE_RIFE = 96
NODE_CLEAN_VRAM = 97
NODE_RESOLUTION = 98
NODE_DURATION = 102
NODE_PROMPT = 107
NODE_UPSCALER = 111
NODE_SEED = 118
NODE_NOISE = 119
NODE_SPECTRUM = 122
NODE_SIGMA_SHIFT = 123
NODE_INT8 = 124
NODE_VAE_DECODE = 125
NODE_SWITCH_QUANT = 126
NODE_SWITCH_CACHE = 127
NODE_H3_CACHE = 128
NODE_VIDEO_COMBINE = 110

FIXED_SEED = 914265959575104

BASELINE_PROMPT = (
    "The scene animates from the first frame. Steam billows heavily from under "
    "the car hood. The older man exhales a tired sigh and slumps slightly. The "
    "overhead light flickers. The younger man tightens his grip on the wrench, "
    "steps forward, and angrily points it toward the engine while shouting. A "
    "sudden burst of sparks shoots up from the engine bay, casting a bright "
    "orange flash across both men's faces as the camera quickly zooms in on the "
    "younger man."
)

NVFP4_UNET = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
INT8_UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
