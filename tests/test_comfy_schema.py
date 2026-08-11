"""Node schemas: what the installed ComfyUI accepts, and what it would reject."""

from __future__ import annotations

import pytest

from h3lab.comfy.schema import NodeSchema, Schemas, parse_schema, static_schemas

INFO = {
    "MiniMaxH3TurboLoRA": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "lora_name": [["turbo_a.safetensors", "turbo_b.safetensors"]],
                "strength": ["FLOAT", {"default": 1.0}],
                "low_vram": ["BOOLEAN", {"default": False}],
            }
        },
        "input_order": {"required": ["model", "lora_name", "strength", "low_vram"]},
        "output": ["MODEL"],
    },
    "MiniMaxH3ReferenceToVideo": {
        "input": {
            "required": {"clip": ["CLIP"], "prompt": ["STRING", {"multiline": True}]},
            "optional": {"ref_images": ["COMFY_MULTIGROW_V3"]},
        },
        "output": ["CONDITIONING", "LATENT"],
    },
}


@pytest.fixture(scope="module")
def schemas() -> Schemas:
    return Schemas(INFO)


def test_a_class_reports_its_widgets_in_the_order_comfyui_declares_them(schemas):
    schema = schemas.get("MiniMaxH3TurboLoRA")
    assert schema.widget_names == ("lora_name", "strength", "low_vram")
    assert "model" not in schema.widget_names  # a link, not a widget


def test_a_combo_input_carries_its_options(schemas):
    assert schemas.combo("MiniMaxH3TurboLoRA", "lora_name") == (
        "turbo_a.safetensors",
        "turbo_b.safetensors",
    )


def test_an_autogrow_input_is_known_by_its_prefix(schemas):
    schema = schemas.get("MiniMaxH3ReferenceToVideo")
    assert schema.knows("ref_images.ref_image_0")
    assert not schema.knows("ref_bananas.ref_banana_0")


def test_a_saved_node_outranks_the_schema_for_widget_order(schemas):
    saved = {
        "type": "MiniMaxH3TurboLoRA",
        "inputs": [
            {"name": "model", "type": "MODEL"},
            {"name": "lora_name", "widget": {"name": "lora_name"}},
            {"name": "strength", "widget": {"name": "strength"}},
        ],
    }
    assert schemas.widget_names("MiniMaxH3TurboLoRA", saved) == ["lora_name", "strength"]


def test_a_node_that_declares_nothing_falls_back_to_the_schema(schemas):
    assert schemas.widget_names("MiniMaxH3TurboLoRA", {"type": "MiniMaxH3TurboLoRA"}) == (
        "lora_name",
        "strength",
        "low_vram",
    )


def test_an_unknown_class_falls_back_to_the_snapshot(schemas):
    assert schemas.widget_names("UNETLoader", {"type": "UNETLoader"}) == [
        "unet_name",
        "weight_dtype",
    ]


# --- validation ------------------------------------------------------------


def test_a_renamed_widget_is_reported_before_comfyui_sees_it(schemas):
    prompt = {
        "9": {
            "class_type": "MiniMaxH3TurboLoRA",
            "inputs": {"model": ["1", 0], "lora_name": "turbo_a.safetensors", "strength_model": 1},
        }
    }
    assert any("strength_model" in note for note in schemas.notes(prompt))


def test_an_input_the_node_grows_at_runtime_is_not_called_a_problem(schemas):
    """`VHS_VideoCombine` sprouts `crf` once a format is chosen; ComfyUI ignores the rest."""
    prompt = {
        "9": {
            "class_type": "MiniMaxH3TurboLoRA",
            "inputs": {
                "model": ["1", 0],
                "lora_name": "turbo_a.safetensors",
                "strength": 1,
                "low_vram": False,
                "crf": 12,
            },
        }
    }
    assert schemas.problems(prompt) == []
    assert schemas.notes(prompt) == ["9 (MiniMaxH3TurboLoRA): unknown input 'crf'"]


def test_a_missing_required_input_is_reported(schemas):
    prompt = {"9": {"class_type": "MiniMaxH3TurboLoRA", "inputs": {"model": ["1", 0]}}}
    assert any("lora_name" in problem for problem in schemas.problems(prompt))


def test_a_lora_file_that_is_not_installed_is_reported(schemas):
    prompt = {
        "9": {
            "class_type": "MiniMaxH3TurboLoRA",
            "inputs": {"model": ["1", 0], "lora_name": "gone.safetensors", "strength": 1},
        }
    }
    assert any("gone.safetensors" in problem for problem in schemas.problems(prompt))


def test_an_uninstalled_class_is_reported(schemas):
    prompt = {"9": {"class_type": "NoSuchNode", "inputs": {}}}
    assert schemas.problems(prompt) == ["9: ComfyUI has no node class 'NoSuchNode'"]


def test_a_valid_prompt_has_no_problems(schemas):
    prompt = {
        "9": {
            "class_type": "MiniMaxH3TurboLoRA",
            "inputs": {
                "model": ["1", 0],
                "lora_name": "turbo_b.safetensors",
                "strength": 0.8,
                "low_vram": False,
            },
        }
    }
    assert schemas.problems(prompt) == []


def test_a_widget_the_node_grew_since_the_template_was_saved_gets_its_default(schemas):
    prompt = {
        "9": {
            "class_type": "MiniMaxH3TurboLoRA",
            "inputs": {"model": ["1", 0], "lora_name": "turbo_b.safetensors", "strength": 0.8},
        }
    }
    assert schemas.fill_defaults(prompt) == ["9.low_vram=False"]
    assert prompt["9"]["inputs"]["low_vram"] is False
    assert schemas.problems(prompt) == []


def test_an_autogrow_input_satisfies_its_declared_parent(schemas):
    prompt = {
        "5": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {"clip": ["2", 0], "prompt": "hello", "ref_images.ref_image_0": ["20", 0]},
        }
    }
    assert schemas.problems(prompt) == []


def test_without_a_running_comfyui_nothing_is_claimed():
    empty = static_schemas()
    assert not empty
    assert empty.problems({"9": {"class_type": "NoSuchNode", "inputs": {}}}) == []
    assert empty.accepts("NoSuchNode", "anything")


def test_a_client_that_cannot_be_reached_leaves_the_schemas_empty():
    class Dead:
        def object_info_all(self):
            raise RuntimeError("connection refused")

    assert not Schemas.from_client(Dead())


def test_a_schema_parsed_from_an_empty_entry_stays_usable():
    schema = parse_schema("Weird", {})
    assert isinstance(schema, NodeSchema)
    assert schema.widget_names == ()
    assert not schema.knows("anything")
