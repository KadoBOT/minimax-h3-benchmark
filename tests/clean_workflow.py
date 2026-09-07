import importlib
import json
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "comfyui-h3-clean"
package = ModuleType("h3_clean_test")
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package
adapter = importlib.import_module("h3_clean_test.workflow")
editor = importlib.import_module("h3_clean_test.editor")
SCHEMAS = json.loads((ROOT / "tests/fixtures/h3_node_schemas.json").read_text(encoding="utf-8"))


def build(inputs, directory=None):
    return adapter.build(inputs, workflow_dir=directory or COMPONENT / "workflows", node_info=SCHEMAS.__getitem__)


def workflow(preset="quality"):
    return json.loads((COMPONENT / "workflows" / adapter.WORKFLOW_FILES[preset]).read_text(encoding="utf-8"))
