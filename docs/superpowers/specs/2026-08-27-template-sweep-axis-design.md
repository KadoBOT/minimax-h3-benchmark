# Template sweep axis

## Goal

h3bench must benchmark packaged MiniMax H3 Studio templates as one coherent
sweep axis. A user can compare any subset of the 83 templates against the
current Studio settings without translating a template into its 27 managed
controls by hand.

The custom node remains the only owner of template definitions. h3bench consumes
the resolved catalog from the Studio manifest and never copies template values
into a second catalog.

## User experience

The sweep builder offers a `Template` axis whenever the Studio session contains
a supported template catalog. Adding it opens a searchable, category-grouped
multi-select rather than rendering 83 ordinary value chips.

The first available arm is `Current settings`. Packaged arms show the same name,
category, evidence status, description, trade-off, tags, and unmet requirements
as the Studio selector. Unavailable templates remain visible but cannot be
selected.

Adding the axis initially selects `Current settings` and the currently selected
packaged template. If the current config has no packaged provenance, it selects
`Current settings` and `Essentials / Balanced`. Users may remove either and
select any other combination. Existing preview, run-count, duplicate, repeat,
and seed controls continue to apply.

## Axis contract

The API represents the virtual axis as:

```json
{
  "field": "template",
  "values": ["__current__", "motion/extreme-action-derope"]
}
```

Packaged values are stable catalog IDs. `__current__` means an unchanged
snapshot of the request's base `GenerationConfig`; it is not a packaged
template and is never sent to the custom node catalog.

The `template` field is accepted only as a sweep axis. It is not a
`GenerationConfig` field, Studio input, benchmark preset field, or mutable
template definition.

## Resolution and data flow

The browser reads names and IDs from `StudioSession.template_catalog` and sends
only selected IDs.

For preview and queue requests, the lab fetches the current Studio manifest and
builds a request-scoped template resolver. The resolver:

1. validates the catalog version and each requested ID;
2. evaluates template requirements against the base Studio inputs and manifest
   capabilities;
3. converts the template's Studio-dialect value map through the existing
   `studio_patch` boundary;
4. merges the resulting concrete top-level and widget values into the base
   config;
5. records immutable provenance in `widgets.h3s_ui`; and
6. returns ordinary `GenerationConfig` instances to preview, duplicate
   detection, storage, and execution.

The resolver is passed explicitly into sweep expansion. The domain sweep module
knows that `template` is a virtual axis but does not fetch manifests or import
HTTP/client concerns.

Template application happens before every allowed ordinary axis. This ordering
is deterministic, although overlap validation means an ordinary axis cannot
replace a template-managed value.

## Overlap rules

Template is mutually exclusive with every template-managed axis and with
controls whose effective value is derived from one:

- sampling steps, scheduler, and sampler;
- cache enablement, family, and preset;
- Turbo enablement, LoRA, LoRA strength, and derived step count;
- attention backend and attention preset;
- all motion, SLA, AdaLN, fp16 accumulation, and ER-SDE controls;
- interpolation, RTX/LTX upscaling, post grade, and cleanup controls.

It may compose with non-overlapping dimensions such as diffusion model,
generation mode, prompt/media inputs, aspect ratio, megapixels, duration, and
the repeat/seed strategy.

The frontend removes conflicting axes from the add-axis choices while Template
is active and refuses to add Template over an existing conflict. The backend
enforces the same rule for direct API clients and returns a 422 naming all
conflicts.

## Requirements and failures

Unknown IDs, unsupported catalog versions, and missing catalogs fail preview
and queue requests with an actionable 422.

A template with unmet requirements is disabled in the chooser. The backend
rechecks requirements so a hand-written or stale request cannot bypass them.
Examples include a Turbo template with no selected Turbo LoRA and an RTX
template when the capability is unavailable. No partial template patch is ever
applied.

If the catalog changes after the browser session, the backend resolves only IDs
that still exist in the current catalog. Removed IDs fail rather than silently
mapping to another template.

## Identity and provenance

`h3s_ui` records the template ID and display name for each generated arm.
`Current settings` receives explicit current-settings provenance. This metadata
supports run labels and historical Template insights.

Provenance does not affect pixels and is excluded from `config_hash` and
`recipe_hash`. Therefore an exact current config and a packaged template that
resolve to the same concrete settings are recognized as duplicates.

All concrete template-managed values remain in the stored `GenerationConfig`.
Old runs are reproducible even if a later catalog changes; execution never
reapplies a template ID from storage.

## Insights

Template becomes a categorical insights axis. Its displayed value comes from
the stored provenance name, with the stable ID as fallback.

For paired analysis, Template is treated as one compound intervention. Matching
keys exclude the concrete top-level and widget fields controlled or derived by
the template, while retaining model, content, canvas, duration, seed, and other
unmanaged settings. This lets two template arms at the same seed form a
controlled pair instead of being rejected as 27 unrelated differences.

Runs without template-axis provenance are not mislabeled as a packaged
template. They appear as `Current settings` only when that sentinel was
explicitly used; otherwise they remain outside Template-axis analysis.

## Compatibility

Ordinary scalar axes, stored runs, custom node workflows, and direct
single-generation Studio controls retain their current contracts. The default
workflow and base generation config are unchanged unless a Template axis is
selected.

The current catalog remains read-only. No create, update, rename, or delete
endpoint is introduced.

## Verification

Tests and gates must prove:

1. the Template axis is absent when no valid catalog is available;
2. all 83 packaged IDs and `Current settings` are searchable/selectable in the
   real h3bench sweep builder;
3. preview expands selected IDs into the exact resolved template values while
   preserving content and canvas settings;
4. overlap conflicts are rejected in both UI and API paths;
5. unknown IDs and unmet requirements fail before queueing without partial
   application;
6. current and packaged arms deduplicate by concrete settings rather than
   provenance;
7. run storage retains concrete values and readable provenance without
   reapplying the catalog;
8. Template insights produce seed-matched comparisons across compound setting
   changes; and
9. complete backend, frontend, live-browser, default-render, and experimental
   render regressions remain green.
