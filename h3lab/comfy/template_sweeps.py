"""Resolve the Studio template axis into concrete generation configs."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from h3lab.comfy.studio import StudioContractError, studio_inputs, studio_patch
from h3lab.domain.config import (
    CURRENT_TEMPLATE_ID,
    TEMPLATE_AXIS_FIELD,
    GenerationConfig,
    spectrum_cache_compatible,
)
from h3lab.domain.sweeps import SweepSpec, TemplateResolver

TEMPLATE_AXIS_CONFLICTS = frozenset(
    {
        "steps",
        "scheduler",
        "sampler",
        "sampler_name",
        "cache_enabled",
        "cache",
        "cache_preset",
        "turbo",
        "turbo_lora",
        "turbo_lora_strength",
        "attn",
        "sol_attn",
        "sol_preset",
        "clean_vram",
        "fp16_accum",
        "derope",
        "post_grade",
        "interp",
        "interpolation",
        "upscaler",
        "upscale_rtx",
        "upscale_ltx",
        "shift_video",
        "shift_audio",
        "sla",
        "sla_sparsity",
        "sla_block_size",
        "sla_dense_last_steps",
        "sla_protect_audio",
        "sla_stabilize_motion",
        "adaln",
        "er_sde",
        "er_sde_solver",
        "er_sde_max_stage",
        "er_sde_eta",
        "er_sde_s_noise",
    }
)


def template_axis_conflicts(
    spec: SweepSpec,
    managed_keys: Iterable[str],
) -> set[str]:
    fields = {axis.field for axis in spec.axes}
    if TEMPLATE_AXIS_FIELD not in fields:
        return set()
    return (fields - {TEMPLATE_AXIS_FIELD}) & (
        TEMPLATE_AXIS_CONFLICTS | set(managed_keys)
    )


def _requirement_failures(
    template: Mapping[str, Any],
    inputs: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> list[str]:
    failures: list[str] = []
    requirements = template.get("requirements")
    if not isinstance(requirements, list):
        return failures
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            continue
        kind = requirement.get("kind")
        key = requirement.get("key")
        expected = requirement.get("value", True)
        if not isinstance(key, str):
            continue
        if kind == "input_not" and (
            inputs.get(key) is None or inputs.get(key) == expected
        ):
            failures.append(str(requirement.get("message") or f"{key} is required"))
        elif kind == "input_equals" and inputs.get(key) != expected:
            failures.append(str(requirement.get("message") or f"{key} must be {expected}"))
        elif kind == "input_in":
            values = requirement.get("values")
            if not isinstance(values, list) or inputs.get(key) not in values:
                failures.append(str(requirement.get("message") or f"{key} must be one of {values}"))
        elif kind == "capability" and capabilities.get(key) != expected:
            failures.append(str(requirement.get("message") or f"{key} is unavailable"))
    return failures


def _state(template_id: str, template_name: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "template_id": template_id,
            "template_name": template_name,
            "source": "sweep",
        },
        separators=(",", ":"),
    )


def make_template_resolver(
    manifest: Mapping[str, Any],
    spec: SweepSpec,
) -> TemplateResolver:
    catalog = manifest.get("template_catalog")
    if not isinstance(catalog, Mapping) or catalog.get("version") not in (1, 2):
        raise StudioContractError(
            "invalid_inputs",
            "template axis requires a supported Studio template catalog",
        )
    managed_keys = catalog.get("managed_keys")
    templates_raw = catalog.get("templates")
    if not isinstance(managed_keys, list) or not isinstance(templates_raw, list):
        raise StudioContractError(
            "invalid_inputs",
            "Studio template catalog is malformed",
        )

    template_axes = [axis for axis in spec.axes if axis.field == TEMPLATE_AXIS_FIELD]
    if len(template_axes) != 1:
        raise StudioContractError(
            "invalid_inputs",
            "a sweep must contain exactly one template axis",
        )

    conflicts = template_axis_conflicts(spec, managed_keys)
    if conflicts:
        raise StudioContractError(
            "invalid_inputs",
            "template axis overlaps with: " + ", ".join(sorted(conflicts)),
        )

    templates: dict[str, Mapping[str, Any]] = {}
    for template in templates_raw:
        if not isinstance(template, Mapping):
            continue
        template_id = template.get("id")
        name = template.get("name")
        values = template.get("values")
        if isinstance(template_id, str) and isinstance(name, str) and isinstance(values, Mapping):
            templates[template_id] = template

    requested = {str(value) for value in template_axes[0].values}
    unknown = sorted(requested - {CURRENT_TEMPLATE_ID} - set(templates))
    if unknown:
        raise StudioContractError(
            "invalid_inputs",
            "unknown Studio template IDs: " + ", ".join(unknown),
        )

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, Mapping):
        capabilities = {}

    def resolve(base: GenerationConfig, template_id: str) -> GenerationConfig:
        if template_id == CURRENT_TEMPLATE_ID:
            if (
                base.cache_active
                and base.cache == "spectrum"
                and not spectrum_cache_compatible(base.sampler, base.widgets)
            ):
                base = base.merged(cache="none", cache_enabled=False)
            return base.merged(
                widgets={"h3s_ui": _state(CURRENT_TEMPLATE_ID, "Current settings")}
            )

        template = templates[template_id]
        failures = _requirement_failures(template, studio_inputs(base), capabilities)
        if failures:
            raise StudioContractError(
                "invalid_inputs",
                f"template {template['name']!r} is unavailable: " + " ".join(failures),
            )

        patch = studio_patch(base, template["values"])
        widgets = dict(patch.pop("widgets", {}))
        widgets["h3s_ui"] = _state(template_id, str(template["name"]))
        return base.merged(**patch, widgets=widgets)

    return resolve
