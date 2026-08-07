from pathlib import Path
import json
from bench.constants import WORKFLOW_PATH, FIXED_SEED, NODE_GGUF, NODE_TURBO_LORA


def test_v3_workflow_exists_and_has_gguf_turbo():
    assert WORKFLOW_PATH.is_file()
    data = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    ids = {n["id"] for n in data["nodes"]}
    assert NODE_GGUF in ids
    assert NODE_TURBO_LORA in ids
    assert FIXED_SEED == 42
