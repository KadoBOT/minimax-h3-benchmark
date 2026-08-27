# Template Sweep Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Workspace rules prohibit subagents, so execute every task inline.

**Goal:** Make all packaged MiniMax H3 Studio templates and the current Studio settings selectable as one searchable h3bench sweep axis with correct resolution, conflicts, identity, and insights.

**Architecture:** The browser sends stable template IDs from the Studio manifest. A request-scoped backend resolver validates those IDs and requirements, translates their Studio value maps through `studio_patch`, and supplies concrete `GenerationConfig` instances to the existing sweep engine. Template provenance remains in `h3s_ui` for display but is excluded from pixel identity; insights treat every template-managed setting as one compound axis.

**Tech Stack:** Python 3.14, Pydantic 2, FastAPI, React 19, TypeScript 6, Vitest, Testing Library, Playwright, pytest.

## Global Constraints

- `studio_templates.json` in `minimax-h3-studio` remains the only template catalog.
- The axis field is exactly `template`; the current-settings sentinel is exactly `__current__`.
- Template is exclusive with all managed and dependent axes.
- Template resolution must happen during preview/queue expansion, never during worker execution.
- Store concrete values for reproducibility; never reapply a stored template ID.
- `h3s_ui` provenance must not affect `config_hash` or `recipe_hash`.
- Preserve prompt, mode, duration, canvas, seed, media, references, and guides.
- Do not add template create, edit, rename, or delete endpoints.
- Do not add dependencies.

## File map

### comfyui-minimax-h3-stack

- Modify `custom_nodes/minimax-h3-studio/web/template_runtime.mjs`: recognize
  sweep provenance and the reserved current-settings sentinel.
- Modify `tests/template_runtime.test.mjs`: prove provenance compatibility.

### minimax-h3-benchmark

- Modify `h3lab/domain/config.py`: parse template provenance and exclude
  `h3s_ui` from sampling identity.
- Modify `h3lab/domain/sweeps.py`: accept the virtual axis and resolve it
  through one explicit callback.
- Create `h3lab/comfy/template_sweeps.py`: validate conflicts, requirements,
  IDs, and turn catalog values into concrete configs.
- Modify `h3lab/engine/lab.py`: construct and pass the request-scoped resolver
  for preview and queue.
- Modify `h3lab/domain/insights.py`: expose Template and pair it as a compound
  intervention.
- Create `web/src/pages/lab/template-sweep-picker.tsx`: searchable grouped
  template multi-select.
- Modify `web/src/pages/lab/sweep-options.ts`: offer Template and publish the
  frontend conflict contract.
- Modify `web/src/pages/lab/sweep-builder.tsx`: initialize and render the
  special axis and enforce conflicts.
- Modify focused Python and web tests listed by each task.

### Local acceptance gates

- Modify `.h3bench/ui/browser_check.mjs`, `.h3bench/ui/check.sh`, and
  `.h3bench/ui/GATES.md`: prove real h3bench selection and preview.
- Modify `.h3bench/exp/benchaxes.py`: include the virtual axis in the matrix
  and insights acceptance check.

---

### Task 1: Provenance and pixel identity

**Files:**
- Modify: `/home/kadobot/Projects/comfyui-minimax-h3-stack/custom_nodes/minimax-h3-studio/web/template_runtime.mjs`
- Modify: `/home/kadobot/Projects/comfyui-minimax-h3-stack/tests/template_runtime.test.mjs`
- Modify: `h3lab/domain/config.py`
- Modify: `tests/test_domain_config.py`

**Interfaces:**
- Produces `TEMPLATE_AXIS_FIELD = "template"`,
  `CURRENT_TEMPLATE_ID = "__current__"`.
- Produces
  `template_provenance(cfg: GenerationConfig) -> tuple[str, str] | None`.
- Extends `canonical_form(..., exclude_widgets: Iterable[str] = ())`.
- `parseTemplateState` preserves optional `template_name` and `source`.

- [ ] **Step 1: Write failing Python identity/provenance tests**

Add to `tests/test_domain_config.py`:

```python
from h3lab.domain.config import (
    CURRENT_TEMPLATE_ID,
    template_provenance,
)


def test_template_provenance_does_not_change_pixel_or_recipe_identity(base_config):
    state = json.dumps(
        {
            "version": 1,
            "template_id": "motion/extreme-action-derope",
            "template_name": "Extreme Action De-rope",
            "source": "sweep",
        },
        separators=(",", ":"),
    )
    tagged = base_config.merged(widgets={"h3s_ui": state})

    assert config_hash(tagged) == config_hash(base_config)
    assert recipe_hash(tagged) == recipe_hash(base_config)
    assert template_provenance(tagged) == (
        "motion/extreme-action-derope",
        "Extreme Action De-rope",
    )


def test_only_sweep_provenance_participates_in_template_insights(base_config):
    ordinary = base_config.merged(
        widgets={
            "h3s_ui": '{"version":1,"template_id":"essentials/balanced"}'
        }
    )
    current = base_config.merged(
        widgets={
            "h3s_ui": (
                '{"version":1,"template_id":"__current__",'
                '"template_name":"Current settings","source":"sweep"}'
            )
        }
    )

    assert template_provenance(ordinary) is None
    assert template_provenance(current) == (
        CURRENT_TEMPLATE_ID,
        "Current settings",
    )


def test_canonical_form_can_exclude_selected_widget_keys(base_config):
    cfg = base_config.merged(widgets={"sla": True, "other": 3})
    payload = json.loads(canonical_form(cfg, exclude_widgets={"sla"}))

    assert payload["widgets"] == {"other": 3}
```

- [ ] **Step 2: Run the focused Python tests and verify RED**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest \
  tests/test_domain_config.py::test_template_provenance_does_not_change_pixel_or_recipe_identity \
  tests/test_domain_config.py::test_only_sweep_provenance_participates_in_template_insights \
  tests/test_domain_config.py::test_canonical_form_can_exclude_selected_widget_keys -q
```

Expected: import/signature failures because the provenance contract does not
exist and `h3s_ui` is still hashed.

- [ ] **Step 3: Implement Python provenance and filtering**

In `h3lab/domain/config.py`, add:

```python
TEMPLATE_AXIS_FIELD = "template"
CURRENT_TEMPLATE_ID = "__current__"
TEMPLATE_STATE_KEY = "h3s_ui"


def template_provenance(cfg: GenerationConfig) -> tuple[str, str] | None:
    raw = cfg.widgets.get(TEMPLATE_STATE_KEY)
    if not isinstance(raw, str):
        return None
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("source") != "sweep"
        or not isinstance(state.get("template_id"), str)
    ):
        return None
    template_id = state["template_id"]
    name = state.get("template_name")
    return template_id, name if isinstance(name, str) and name else template_id
```

Extend `canonical_form`:

```python
def canonical_form(
    cfg: GenerationConfig,
    *,
    exclude: Iterable[str] = (),
    exclude_widgets: Iterable[str] = (),
) -> str:
    skip = set(exclude)
    skipped_widgets = {TEMPLATE_STATE_KEY, *exclude_widgets}
    payload = {
        field: _jsonable(
            {
                key: value
                for key, value in cfg.widgets.items()
                if key not in skipped_widgets
                and (key != "attn" or value not in {"sol", "off"})
            }
            if field == "widgets"
            else getattr(cfg, field)
        )
        for field in HASHED_FIELDS
        if field not in skip
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

- [ ] **Step 4: Write failing shared-runtime provenance tests**

Add to the stack's `tests/template_runtime.test.mjs`:

```javascript
test('sweep provenance remains compatible and current settings read as custom', () => {
  const packaged = parseTemplateState(
    '{"version":1,"template_id":"essentials/balanced","template_name":"Balanced","source":"sweep"}',
  );
  assert.deepEqual(packaged, {
    version: 1,
    template_id: 'essentials/balanced',
    template_name: 'Balanced',
    source: 'sweep',
  });

  const current = templateMatch(
    CATALOG,
    {
      steps: 12,
      cache: false,
      h3s_ui:
        '{"version":1,"template_id":"__current__","template_name":"Current settings","source":"sweep"}',
    },
  );
  assert.equal(current.kind, 'custom');
  assert.equal(current.template, null);
});
```

- [ ] **Step 5: Run the Node test and verify RED**

Run:

```bash
cd /home/kadobot/Projects/comfyui-minimax-h3-stack
node --test tests/template_runtime.test.mjs
```

Expected: the parser drops optional fields and the current sentinel is reported
as unavailable.

- [ ] **Step 6: Implement additive runtime provenance**

Change `parseTemplateState` and `templateMatch`:

```javascript
export function parseTemplateState(raw) {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  try {
    const state = JSON.parse(raw);
    if (state?.version !== 1 || typeof state.template_id !== 'string') return null;
    return {
      version: 1,
      template_id: state.template_id,
      ...(typeof state.template_name === 'string'
        ? { template_name: state.template_name }
        : {}),
      ...(typeof state.source === 'string' ? { source: state.source } : {}),
    };
  } catch {
    return null;
  }
}

export function templateMatch(catalog, inputs, rawState = inputs?.h3s_ui) {
  const state = parseTemplateState(rawState);
  if (!state || state.template_id === '__current__') {
    return { kind: 'custom', template: null, state };
  }
  const template = catalog?.templates?.find((item) => item.id === state.template_id);
  if (!template) return { kind: 'unavailable', template: null, state };
  const matches = catalog.managed_keys.every(
    (key) => sameValue(inputs?.[key], template.values[key]),
  );
  return { kind: matches ? 'match' : 'custom', template, state };
}
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest tests/test_domain_config.py -q
cd /home/kadobot/Projects/comfyui-minimax-h3-stack
node --test tests/template_runtime.test.mjs
```

Expected: both commands pass.

- [ ] **Step 8: Commit each repository**

Commit the stack runtime/test as:

```text
Support sweep provenance in Studio templates
```

Commit h3bench config/test as:

```text
Exclude template provenance from run identity
```

Use explicit path-only commits so the pre-existing package-manager migration
stays staged but uncommitted.

---

### Task 2: Authoritative backend template expansion

**Files:**
- Create: `h3lab/comfy/template_sweeps.py`
- Modify: `h3lab/domain/sweeps.py`
- Modify: `h3lab/engine/lab.py`
- Create: `tests/test_template_sweeps.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces
  `make_template_resolver(manifest: Mapping[str, Any], spec: SweepSpec) -> TemplateResolver`.
- Produces
  `template_axis_conflicts(spec: SweepSpec, managed_keys: Iterable[str]) -> set[str]`.
- Defines
  `TemplateResolver = Callable[[GenerationConfig, str], GenerationConfig]`.
- Extends `expand` and `preview` with optional keyword
  `template_resolver: TemplateResolver | None = None`.

- [ ] **Step 1: Write failing resolver tests**

Create `tests/test_template_sweeps.py` with a two-template catalog and tests:

```python
import pytest

from h3lab.comfy.studio import studio_inputs
from h3lab.comfy.template_sweeps import make_template_resolver
from h3lab.domain.config import CURRENT_TEMPLATE_ID, config_hash
from h3lab.domain.sweeps import SweepAxis, SweepSpec, expand


CATALOG = {
    "version": 1,
    "managed_keys": [
        "steps",
        "scheduler",
        "sampler_name",
        "turbo",
        "cache",
        "attn",
    ],
    "categories": [{"id": "essentials", "name": "Essentials"}],
    "templates": [
        {
            "id": "essentials/balanced",
            "name": "Balanced",
            "requirements": [],
            "values": {
                "steps": 20,
                "scheduler": "simple",
                "sampler_name": "euler",
                "turbo": False,
                "cache": True,
                "attn": "sol",
            },
        },
        {
            "id": "essentials/turbo",
            "name": "Turbo",
            "requirements": [
                {
                    "kind": "input_not",
                    "key": "turbo_lora",
                    "value": "none",
                    "message": "Select a Turbo LoRA first.",
                }
            ],
            "values": {
                "steps": 4,
                "scheduler": "simple",
                "sampler_name": "euler",
                "turbo": True,
                "cache": True,
                "attn": "sol",
            },
        },
    ],
}


def manifest():
    return {
        "template_catalog": CATALOG,
        "capabilities": {"turbo": True},
    }


def test_template_axis_expands_current_and_packaged_values(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=(
            SweepAxis(
                field="template",
                values=(CURRENT_TEMPLATE_ID, "essentials/balanced"),
            ),
        ),
    )
    resolver = make_template_resolver(manifest(), spec)
    current, balanced = expand(spec, template_resolver=resolver)

    assert studio_inputs(current)["steps"] == base_config.steps
    assert studio_inputs(balanced)["steps"] == 20
    assert studio_inputs(balanced)["scheduler"] == "simple"
    assert config_hash(current) == config_hash(base_config)
    assert '"source":"sweep"' in current.widgets["h3s_ui"]
    assert '"template_id":"essentials/balanced"' in balanced.widgets["h3s_ui"]


def test_template_axis_applies_before_a_non_overlapping_axis(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=(
            SweepAxis(field="template", values=("essentials/balanced",)),
            SweepAxis(field="mp", values=(0.5, 1.0)),
        ),
    )
    configs = expand(spec, template_resolver=make_template_resolver(manifest(), spec))

    assert [config.mp for config in configs] == [0.5, 1.0]
    assert all(config.steps == 20 for config in configs)


@pytest.mark.parametrize("field", ["steps", "turbo_lora", "cache_preset", "sol_preset", "sla"])
def test_template_axis_rejects_managed_and_dependent_axes(base_config, field):
    spec = SweepSpec(
        base=base_config,
        axes=(
            SweepAxis(field="template", values=("essentials/balanced",)),
            SweepAxis(field=field, values=(1, 2)),
        ),
    )
    with pytest.raises(ValueError, match=field):
        make_template_resolver(manifest(), spec)


def test_template_axis_rejects_unknown_and_unavailable_values(base_config):
    unknown = SweepSpec(
        base=base_config,
        axes=(SweepAxis(field="template", values=("missing/template",)),),
    )
    with pytest.raises(ValueError, match="missing/template"):
        make_template_resolver(manifest(), unknown)

    turbo = SweepSpec(
        base=base_config,
        axes=(SweepAxis(field="template", values=("essentials/turbo",)),),
    )
    with pytest.raises(ValueError, match="Turbo LoRA"):
        expand(turbo, template_resolver=make_template_resolver(manifest(), turbo))
```

Use valid axis values in the parameterized conflict fixture for each field;
the assertion concerns field conflict detection, not scalar validation.

- [ ] **Step 2: Run resolver tests and verify RED**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest tests/test_template_sweeps.py -q
```

Expected: import failure for the new resolver module and rejection of the
unknown `template` axis.

- [ ] **Step 3: Add virtual-axis expansion**

In `h3lab/domain/sweeps.py`:

```python
from collections.abc import Callable

from h3lab.domain.config import (
    TEMPLATE_AXIS_FIELD,
    STUDIO_EXTRA_FIELDS,
    GenerationConfig,
    config_hash,
)

TemplateResolver = Callable[[GenerationConfig, str], GenerationConfig]
VIRTUAL_AXIS_FIELDS = frozenset({TEMPLATE_AXIS_FIELD})
```

Allow `VIRTUAL_AXIS_FIELDS` in `SweepAxis._known_field`. Implement:

```python
def expand(
    spec: SweepSpec,
    *,
    rng: random.Random | None = None,
    template_resolver: TemplateResolver | None = None,
) -> list[GenerationConfig]:
    generator = rng or random.Random()
    configs: list[GenerationConfig] = []
    used_seeds: set[int] = set()

    for combo in _product(spec.axes):
        values = dict(combo)
        template_id = values.pop(TEMPLATE_AXIS_FIELD, None)
        base = spec.base
        if template_id is not None:
            if template_resolver is None:
                raise ValueError("template axis requires the Studio template catalog")
            base = template_resolver(base, str(template_id))
        for repeat in range(spec.repeats):
            overrides = dict(values)
            if spec.seed_strategy == "increment":
                overrides["seed"] = base.seed + repeat
            elif spec.seed_strategy == "random":
                while True:
                    candidate = generator.randrange(0, 2**31 - 1)
                    if candidate not in used_seeds:
                        used_seeds.add(candidate)
                        break
                overrides["seed"] = candidate
            configs.append(base.merged(**overrides))
    return configs
```

Thread `template_resolver` through `preview`.

- [ ] **Step 4: Implement the request-scoped resolver**

Create `h3lab/comfy/template_sweeps.py` with:

```python
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from h3lab.comfy.studio import studio_inputs, studio_patch
from h3lab.domain.config import (
    CURRENT_TEMPLATE_ID,
    TEMPLATE_AXIS_FIELD,
    GenerationConfig,
)
from h3lab.domain.sweeps import SweepSpec, TemplateResolver

TEMPLATE_AXIS_CONFLICTS = frozenset(
    {
        "steps", "scheduler", "sampler", "sampler_name",
        "cache_enabled", "cache", "cache_preset",
        "turbo", "turbo_lora", "turbo_lora_strength",
        "attn", "sol_attn", "sol_preset",
        "clean_vram", "fp16_accum", "derope", "post_grade",
        "interp", "interpolation", "upscaler", "upscale_rtx", "upscale_ltx",
        "shift_video", "shift_audio", "sla", "sla_sparsity",
        "sla_block_size", "sla_dense_last_steps", "sla_protect_audio",
        "sla_stabilize_motion", "adaln", "er_sde", "er_sde_solver",
        "er_sde_max_stage", "er_sde_eta", "er_sde_s_noise",
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
    failures = []
    for requirement in template.get("requirements") or []:
        kind = requirement.get("kind")
        key = requirement.get("key")
        expected = requirement.get("value", True)
        if kind == "input_not" and (
            inputs.get(key) is None or inputs.get(key) == expected
        ):
            failures.append(str(requirement["message"]))
        elif kind == "capability" and capabilities.get(key) != expected:
            failures.append(str(requirement["message"]))
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
    if not isinstance(catalog, Mapping) or catalog.get("version") != 1:
        raise ValueError("template axis requires a supported Studio template catalog")
    templates = {
        template["id"]: template
        for template in catalog.get("templates") or []
        if isinstance(template, Mapping) and isinstance(template.get("id"), str)
    }
    conflicts = template_axis_conflicts(spec, catalog.get("managed_keys") or [])
    if conflicts:
        raise ValueError(
            "template axis overlaps with: " + ", ".join(sorted(conflicts))
        )
    requested = {
        str(value)
        for axis in spec.axes
        if axis.field == TEMPLATE_AXIS_FIELD
        for value in axis.values
    }
    unknown = sorted(requested - {CURRENT_TEMPLATE_ID} - set(templates))
    if unknown:
        raise ValueError("unknown Studio template IDs: " + ", ".join(unknown))
    capabilities = manifest.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, Mapping) else {}

    def resolve(base: GenerationConfig, template_id: str) -> GenerationConfig:
        if template_id == CURRENT_TEMPLATE_ID:
            return base.merged(
                widgets={
                    "h3s_ui": _state(CURRENT_TEMPLATE_ID, "Current settings")
                }
            )
        template = templates[template_id]
        failures = _requirement_failures(
            template,
            studio_inputs(base),
            capabilities,
        )
        if failures:
            raise ValueError(
                f"template {template['name']!r} is unavailable: "
                + " ".join(failures)
            )
        patch = studio_patch(base, template["values"])
        widgets = dict(patch.pop("widgets", {}))
        widgets["h3s_ui"] = _state(template_id, str(template["name"]))
        return base.merged(**patch, widgets=widgets)

    return resolve
```

Keep imports module-scoped and use direct validation; do not add network access
or a second catalog.

- [ ] **Step 5: Wire Lab preview and queue**

In `h3lab/engine/lab.py`, add a private helper:

```python
def _template_resolver(self, spec: SweepSpec):
    if not any(axis.field == "template" for axis in spec.axes):
        return None
    from h3lab.comfy.template_sweeps import make_template_resolver

    return make_template_resolver(self.client.studio_manifest(), spec)
```

Then:

```python
def preview_sweep(self, spec: SweepSpec) -> SweepPreview:
    resolver = self._template_resolver(spec)
    return preview(
        spec,
        existing=self.runs.hashes(),
        template_resolver=resolver,
    )

def run_sweep(self, spec: SweepSpec, *, skip_duplicates: bool = True) -> list[RunView]:
    known = self.runs.hashes() if skip_duplicates else {}
    resolver = self._template_resolver(spec)
    wanted = [
        config
        for config in expand(spec, template_resolver=resolver)
        if config_hash(config) not in known
    ]
    return self.enqueue_many(wanted)
```

The local import avoids a cycle only if the module graph requires it; otherwise
move it to the module import block to follow repository style.

- [ ] **Step 6: Add API contract tests**

In `tests/test_api.py`, extend the stub's `studio_manifest` fixture with a
minimal template catalog, then add tests posting:

```python
{
    "base": config.model_dump(mode="json"),
    "axes": [
        {
            "field": "template",
            "values": ["__current__", "essentials/balanced"],
        }
    ],
}
```

Assert preview returns two configs, the packaged arm has exact concrete values,
content fields are unchanged, provenance is present, and a direct request with
`template + steps` returns 422 mentioning `steps`. Add separate 422 assertions
for an unknown ID and an unmet Turbo requirement.

- [ ] **Step 7: Run backend tests**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest \
  tests/test_template_sweeps.py \
  tests/test_domain_sweeps.py \
  tests/test_api.py -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

Commit only the task files as:

```text
Add authoritative template sweep expansion
```

---

### Task 3: Compound Template insights

**Files:**
- Modify: `h3lab/domain/config.py`
- Modify: `h3lab/domain/insights.py`
- Modify: `tests/test_domain_insights.py`
- Modify: `tests/test_domain_config.py`

**Interfaces:**
- Produces `TEMPLATE_TOP_LEVEL_FIELDS` and `TEMPLATE_WIDGET_FIELDS`.
- `axis_value(..., "template")` returns a provenance label or `None`.
- Template pair keys omit every concrete managed/derived field as one unit.
- Template speed deltas use `wall_s`; all existing axes continue using
  `sec_per_it`.

- [ ] **Step 1: Write failing insight tests**

Add to `tests/test_domain_insights.py`:

```python
def template_state(template_id: str, name: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "template_id": template_id,
            "template_name": name,
            "source": "sweep",
        },
        separators=(",", ":"),
    )


def test_template_is_a_compound_seed_matched_insight(base_config):
    runs = []
    for seed in (1, 2):
        stem = base_config.merged(seed=seed)
        balanced = stem.merged(
            steps=20,
            scheduler="simple",
            widgets={
                "derope": False,
                "h3s_ui": template_state("essentials/balanced", "Balanced"),
            },
        )
        action = stem.merged(
            steps=28,
            scheduler="beta57",
            widgets={
                "derope": True,
                "h3s_ui": template_state(
                    "motion/extreme-action-derope",
                    "Extreme Action De-rope",
                ),
            },
        )
        runs.extend(
            [
                make_run(f"b{seed}", balanced, stars=6, rate=5),
                make_run(f"a{seed}", action, stars=8, rate=9),
            ]
        )

    insight = analyse(runs, "template")
    comparison = insight.paired[0]
    assert set(insight.values) == {"Balanced", "Extreme Action De-rope"}
    assert comparison.pair_groups == 2
    assert comparison.matched_on == "seed"
    assert insight.quality_verdict.value == "Extreme Action De-rope"
    assert insight.speed_verdict.value == "Balanced"


def test_template_axis_ignores_runs_without_sweep_provenance(base_config):
    ordinary = make_run(
        "ordinary",
        base_config.merged(
            widgets={
                "h3s_ui": (
                    '{"version":1,"template_id":"essentials/balanced"}'
                )
            }
        ),
    )
    current = make_run(
        "current",
        base_config.merged(
            widgets={
                "h3s_ui": template_state("__current__", "Current settings")
            }
        ),
    )

    assert marginal([ordinary, current], "template")[0].value == "Current settings"
    assert "template" not in {
        axis.field for axis in available_axes([ordinary, current])
    }
```

Import `json`.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest \
  tests/test_domain_insights.py::test_template_is_a_compound_seed_matched_insight \
  tests/test_domain_insights.py::test_template_axis_ignores_runs_without_sweep_provenance -q
```

Expected: unknown insight axis and/or no matched pairs.

- [ ] **Step 3: Implement compound exclusion constants**

In `h3lab/domain/config.py` define:

```python
TEMPLATE_TOP_LEVEL_FIELDS = frozenset(
    {
        "steps", "scheduler", "sampler", "cache_enabled", "cache",
        "turbo", "turbo_lora", "turbo_lora_strength", "sol_attn",
        "clean_vram", "interp", "upscaler",
    }
)
TEMPLATE_WIDGET_FIELDS = frozenset(
    {
        "attn", "shift_video", "shift_audio", "derope", "post_grade",
        "upscale_ltx", "sla", "sla_sparsity", "sla_block_size",
        "sla_dense_last_steps", "sla_protect_audio",
        "sla_stabilize_motion", "adaln", "fp16_accum", "er_sde",
        "er_sde_solver", "er_sde_max_stage", "er_sde_eta",
        "er_sde_s_noise",
    }
)
```

Tests must cross-check this union against the live catalog's 27 managed keys
after applying `STUDIO_FIELD_ALIASES`; update both constants whenever that
catalog contract changes.

- [ ] **Step 4: Add Template to insights**

In `h3lab/domain/insights.py`:

```python
AxisDef(field="template", label="Template", kind="categorical"),
```

Change `axis_value` to return `str | None` and use
`template_provenance(cfg)` for Template. Skip `None` values in `marginal`,
`_compare_within`, and `available_axes`.

Add a helper:

```python
def _match_form(cfg: GenerationConfig, axis: str, *, seed: bool) -> str:
    exclude = _held_apart(axis)
    exclude_widgets: set[str] = set()
    if axis == TEMPLATE_AXIS_FIELD:
        exclude |= set(TEMPLATE_TOP_LEVEL_FIELDS)
        exclude_widgets |= set(TEMPLATE_WIDGET_FIELDS)
    if not seed:
        exclude.add("seed")
    return canonical_form(
        cfg,
        exclude=exclude,
        exclude_widgets=exclude_widgets,
    )
```

Use it from `_seed_matched_key` and `_recipe_matched_key`.

In `_compare_within`, select the timing measure by axis:

```python
def timing(run: InsightRun) -> float | None:
    return run.wall_s if axis == TEMPLATE_AXIS_FIELD else run.sec_per_it

rates_a = [value for run in by_value[value_a] if (value := timing(run))]
rates_b = [value for run in by_value[value_b] if (value := timing(run))]
```

Keep the existing percentage calculation. In `_verdict_from`, use `% faster
end to end` for Template and `% faster per step` for every existing axis.

- [ ] **Step 5: Run insight and config tests**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest \
  tests/test_domain_config.py \
  tests/test_domain_insights.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

Commit only the task files as:

```text
Add compound Template insights
```

---

### Task 4: Searchable grouped Template axis in h3bench

**Files:**
- Create: `web/src/pages/lab/template-sweep-picker.tsx`
- Create: `web/src/pages/lab/template-sweep-picker.test.tsx`
- Modify: `web/src/pages/lab/sweep-options.ts`
- Modify: `web/src/pages/lab/sweep-builder.tsx`
- Modify: `web/src/pages/lab/sweep-builder.test.ts`
- Modify: `web/src/pages/lab/lab.test.tsx`

**Interfaces:**
- Produces `CURRENT_TEMPLATE_ID = "__current__"` in
  `sweep-options.ts`.
- Produces `TEMPLATE_CONFLICT_FIELDS: ReadonlySet<string>`.
- Produces
  `templateRequirementFailures(template, inputs, capabilities) -> string[]`.
- Produces `templateIdFromState(raw: unknown) -> string | null`.
- Produces `TemplateSweepPicker` with selected IDs and `onChange`.

- [ ] **Step 1: Write failing sweep-option tests**

Extend `web/src/pages/lab/sweep-builder.test.ts`:

```typescript
it("offers every packaged template plus current settings", () => {
  const catalog = {
    version: 1 as const,
    managed_keys: ["steps", "derope"],
    selector: { label: "Template", placeholder: "Search templates" },
    categories: [{ id: "essentials", name: "Essentials" }],
    templates: [
      {
        id: "essentials/balanced",
        category: "essentials",
        name: "Balanced",
        description: "General settings.",
        tradeoff: "Balanced speed and quality.",
        evidence: "curated" as const,
        evidence_ref: null,
        tags: ["general"],
        requirements: [],
        values: { steps: 20, derope: false },
      },
    ],
  }
  const axes = sweepable(META, CATALOG, {}, catalog)
  expect(axes.find((axis) => axis.field === "template")?.values).toEqual([
    "__current__",
    "essentials/balanced",
  ])
})

it("does not offer Template without a supported catalog", () => {
  expect(sweepable(META, CATALOG, {}, null).some((axis) => axis.field === "template")).toBe(false)
})
```

- [ ] **Step 2: Write failing picker tests**

Create `template-sweep-picker.test.tsx` using Testing Library. Render two
categories and assert:

- `Current settings` is selectable;
- searching `anime action` leaves only the matching template;
- category headings and evidence badges render;
- clicking a template adds/removes its ID;
- a failed capability requirement disables the choice and displays its message.

Use real `StudioTemplateCatalog` types from `@/lib/studio-runtime`.

- [ ] **Step 3: Run web tests and verify RED**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark/web
npx vitest run \
  src/pages/lab/sweep-builder.test.ts \
  src/pages/lab/template-sweep-picker.test.tsx
```

Expected: missing fourth argument behavior and missing picker module.

- [ ] **Step 4: Extend sweep options and conflicts**

Change `sweepable` to accept:

```typescript
templateCatalog: StudioTemplateCatalog | null | undefined = null
```

Append:

```typescript
if (templateCatalog?.version === 1 && templateCatalog.templates.length) {
  axes.unshift({
    field: "template",
    values: [
      CURRENT_TEMPLATE_ID,
      ...templateCatalog.templates.map((template) => template.id),
    ],
    render: (value) =>
      value === CURRENT_TEMPLATE_ID
        ? "Current settings"
        : templateCatalog.templates.find((template) => template.id === value)?.name
          ?? String(value),
  })
}
```

Export the explicit conflict set matching the backend and test that every
catalog managed key maps to a conflicting frontend field.

Implement the pure helpers in `sweep-options.ts`:

```typescript
export function templateIdFromState(raw: unknown): string | null {
  if (typeof raw !== "string" || !raw.trim()) return null
  try {
    const state = JSON.parse(raw) as { version?: unknown; template_id?: unknown }
    return state.version === 1 && typeof state.template_id === "string"
      ? state.template_id
      : null
  } catch {
    return null
  }
}

export function templateRequirementFailures(
  template: StudioTemplate,
  inputs: Record<string, unknown>,
  capabilities: Record<string, unknown>
): string[] {
  return template.requirements.flatMap((requirement) => {
    const expected = requirement.value ?? true
    const failed =
      requirement.kind === "input_not"
        ? inputs[requirement.key] == null || inputs[requirement.key] === expected
        : capabilities[requirement.key] !== expected
    return failed ? [requirement.message] : []
  })
}
```

- [ ] **Step 5: Implement `TemplateSweepPicker`**

The component signature is:

```typescript
export function TemplateSweepPicker({
  catalog,
  selected,
  inputs,
  capabilities,
  onChange,
}: {
  catalog: StudioTemplateCatalog
  selected: (string | number | boolean)[]
  inputs: Record<string, unknown>
  capabilities: Record<string, unknown>
  onChange: (selected: string[]) => void
})
```

Implement the body with this structure (use the repository's existing border,
text, and signal classes):

```typescript
const [query, setQuery] = useState("")
const picked = new Set(selected.map(String))
const categoryNames = new Map(
  catalog.categories.map((category) => [category.id, category.name])
)
const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
const filtered = catalog.templates.filter((template) => {
  const haystack = [
    template.name,
    categoryNames.get(template.category),
    template.description,
    template.tradeoff,
    template.evidence,
    ...template.tags,
  ].join(" ").toLowerCase()
  return terms.every((term) => haystack.includes(term))
})
const toggle = (id: string) => {
  onChange(
    picked.has(id)
      ? [...picked].filter((value) => value !== id)
      : [...picked, id]
  )
}

return (
  <div className="border-rule space-y-2 rounded-sm border p-2">
    <input
      data-template-axis-search
      aria-label="Search template axis"
      type="search"
      value={query}
      placeholder={catalog.selector.placeholder}
      onChange={(event) => setQuery(event.target.value)}
      className="border-rule bg-ink text-bone w-full rounded-sm border px-2 py-1.5 text-sm"
    />
    <button
      type="button"
      data-template-axis-current
      aria-pressed={picked.has(CURRENT_TEMPLATE_ID)}
      onClick={() => toggle(CURRENT_TEMPLATE_ID)}
    >
      Current settings
    </button>
    {catalog.categories.map((category) => {
      const templates = filtered.filter(
        (template) => template.category === category.id
      )
      if (!templates.length) return null
      return (
        <section key={category.id} data-template-axis-category={category.id}>
          <h4>{category.name}</h4>
          {templates.map((template) => {
            const failures = templateRequirementFailures(
              template,
              inputs,
              capabilities
            )
            return (
              <button
                key={template.id}
                type="button"
                data-template-axis-id={template.id}
                disabled={failures.length > 0}
                aria-pressed={picked.has(template.id)}
                onClick={() => toggle(template.id)}
              >
                <span>{template.name}</span>
                <span>{template.evidence}</span>
                <p>{template.description}</p>
                <p>{template.tradeoff}</p>
                <p>{template.tags.join(" · ")}</p>
                {failures.length ? <p>{failures.join(" ")}</p> : null}
              </button>
            )
          })}
        </section>
      )
    })}
  </div>
)
```

Use actual `disabled` for unavailable templates and these browser hooks:

```text
data-template-axis-search
data-template-axis-current
data-template-axis-id="<template id>"
data-template-axis-category="<category id>"
```

Use the catalog's order and case-insensitive all-term search over name,
category, description, trade-off, evidence, and tags.

- [ ] **Step 6: Integrate the special picker**

In `SweepBuilder`:

- pass `studio.data?.template_catalog` to `sweepable`;
- derive Studio-dialect inputs with
  `studioInputsFromDraft(studio.data, base)`;
- when adding Template, seed with `__current__` and the provenance template ID
  if present, otherwise `essentials/balanced`;
- hide Template when a conflicting axis is active;
- hide conflicting axes when Template is active;
- render `TemplateSweepPicker` instead of generic chips for the template row;
- keep generic axes unchanged.

The integration branch is explicit:

```typescript
const templateCatalog = studio.data?.template_catalog
const templateActive = axes.some((axis) => axis.field === "template")
const conflictingActive = axes.some((axis) =>
  TEMPLATE_CONFLICT_FIELDS.has(axis.field)
)
const addable = available.filter((candidate) => {
  if (candidate.field === "template") return !conflictingActive
  if (templateActive && TEMPLATE_CONFLICT_FIELDS.has(candidate.field)) return false
  return !axes.some((picked) => picked.field === candidate.field)
})

// Inside addAxis:
if (field === "template") {
  const currentTemplate = templateIdFromState(
    (base.widgets?.h3s_ui as string | undefined) ?? ""
  )
  const initial = currentTemplate && currentTemplate !== CURRENT_TEMPLATE_ID
    ? currentTemplate
    : "essentials/balanced"
  setAxes([...axes, { field, values: [CURRENT_TEMPLATE_ID, initial] }])
  return
}

// Inside the axis row:
if (axis.field === "template" && templateCatalog) {
  return (
    <TemplateSweepPicker
      catalog={templateCatalog}
      selected={axis.values}
      inputs={studioInputsFromDraft(studio.data!, base)}
      capabilities={studio.data?.capabilities ?? {}}
      onChange={(values) =>
        setAxes(
          axes.map((item) =>
            item.field === "template" ? { ...item, values } : item
          )
        )
      }
    />
  )
}
```

Do not put Template in `GenerationConfig` and do not alter the ordinary Studio
panel.

- [ ] **Step 7: Add Lab page interaction test**

Extend `lab.test.tsx` to open `Add a sweep axis`, choose Template, search for
`Extreme Action`, select that arm, and assert the preview request contains:

```typescript
axes: [
  {
    field: "template",
    values: ["__current__", "motion/extreme-action-derope"],
  },
]
```

Also assert `Steps` is not offered while Template is active and becomes
available after removing Template.

- [ ] **Step 8: Run web tests and build**

Run:

```bash
cd /home/kadobot/Projects/minimax-h3-benchmark/web
npx vitest run \
  src/pages/lab/sweep-builder.test.ts \
  src/pages/lab/template-sweep-picker.test.tsx \
  src/pages/lab/lab.test.tsx
npm run build
```

Expected: all pass; TypeScript and Vite exit zero.

- [ ] **Step 9: Commit**

Commit only the task files as:

```text
Add searchable Template sweep controls
```

---

### Task 5: Live acceptance, regressions, and persistence

**Files:**
- Modify: `/home/kadobot/ComfyUI/.h3bench/ui/browser_check.mjs`
- Modify: `/home/kadobot/ComfyUI/.h3bench/ui/check.sh`
- Modify: `/home/kadobot/ComfyUI/.h3bench/ui/GATES.md`
- Modify: `/home/kadobot/ComfyUI/.h3bench/exp/benchaxes.py`

**Interfaces:**
- New success token:
  `BENCH_TEMPLATE_AXIS_OK 84 searchable selectable previewed conflicts`.
- Existing template-selection and render tokens remain unchanged.

- [ ] **Step 1: Extend the real-browser gate**

After the current h3bench Studio template checks, automate:

1. open `Add a sweep axis`;
2. choose `Template`;
3. assert 83 packaged choices plus `Current settings`;
4. search `extreme action`;
5. select `motion/extreme-action-derope`;
6. assert Template and Current are selected;
7. assert overlapping axes such as Steps, Attention, and ER-SDE are absent;
8. submit Preview;
9. inspect the captured request and response to prove two concrete configs;
10. assert the action template's steps/de-rope values and unchanged prompt,
    mode, duration, canvas, and seed;
11. print the unique success token only after every assertion.

Update the old `no-axis` token because Template is now intentionally an axis;
ordinary Studio selection still must not require adding one.

- [ ] **Step 2: Extend benchmark-axis acceptance**

Teach `benchaxes.py offered` to validate:

- `template` appears in the matrix and insights registry;
- `__current__` and all 83 manifest IDs are available;
- two representative IDs resolve to distinct concrete config hashes;
- overlapping direct API axes are rejected.

Do not add Template to the existing scalar `AXIS_VALUES` loop because it needs
the request-scoped catalog resolver.

- [ ] **Step 3: Run focused gates**

Restart h3bench so backend code and generated frontend assets are current, then
run:

```bash
cd /home/kadobot/ComfyUI/.h3bench/ui
./check.sh g4
./check.sh g10
cd /home/kadobot/ComfyUI/.h3bench/exp
./check.sh g12
```

Expected: the new axis token and all existing both-host template tokens pass.

- [ ] **Step 4: Run complete repository suites**

```bash
cd /home/kadobot/Projects/comfyui-minimax-h3-stack
/home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests -q
node --test tests/template_runtime.test.mjs

cd /home/kadobot/Projects/minimax-h3-benchmark
.venv/bin/python -m pytest tests -q
cd web
npx vitest run
npm run build
```

Expected: zero failures.

- [ ] **Step 5: Run all UI and workflow gates**

Restart ComfyUI through `/home/kadobot/.local/bin/comfyui` so the WSL CUDA shim
remains active. Restart h3bench with `uv run h3lab serve --no-worker`. Then run
every UI gate and every experiment gate, including:

```bash
cd /home/kadobot/ComfyUI/.h3bench/exp
./check.sh g9
./check.sh g10
```

Expected: the RTX-enabled default render and SLA/ER-SDE render both complete;
installing the Template axis does not alter a non-template run.

- [ ] **Step 6: Final review and commits**

Run:

```bash
git diff --check
```

in the stack repository and the CRLF-aware equivalent in h3bench. Inspect every
staged and untracked file. Keep the pre-existing README/uv migration changes
separate.

Commit local gate changes only if they belong to a product-owned repository;
leave `.h3bench`, `.nvfix`, and standalone NvVFX diagnostics uncommitted in the
ComfyUI core checkout.

- [ ] **Step 7: Push and integrate only after user choice**

Report the exact commits and fresh verification. Then offer:

1. push both feature branches and create PRs;
2. merge locally into stack `main` and benchmark `master`; or
3. keep the committed branches.

Do not push or merge without that explicit choice.
