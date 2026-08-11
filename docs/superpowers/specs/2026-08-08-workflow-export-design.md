# Workflow Export and Frame Interpolation — Design

**Date:** 2026-08-08
**Surface map:** `2026-08-08-workflow-export-surfaces.md`
**Status:** Approved (one-shot: self-approved after spec self-review)

## The problem

Three related complaints, all about the same seam — the boundary where the lab's config meets
a ComfyUI graph.

1. **There is no way to get the graph back out.** The lab patches a template per run and
   submits it; the graph that ran exists only inside the process. A run that produced
   something good cannot be opened in ComfyUI and taken further by hand.
2. **The image ComfyUI saves beside the video is an API dump.** Dragging it back into ComfyUI
   produces the flat, positionless, group-less graph you get from an API JSON, not the
   template's layout. The run's own artifact is therefore useless as a starting point.
3. **Interpolation is a boolean, and RIFE is not the only interpolator.** ComfyUI 0.30 ships
   `FrameInterpolationModelLoader` + `FrameInterpolate` in core, and this machine has
   `film_net_fp16.safetensors` in its `frame_interpolation` folder. The config can only say
   yes or no to RIFE.

## What we know (looked up, not assumed)

- The live ComfyUI (0.30.0) serves `FrameInterpolationModelLoader` (`model_name` COMBO, one
  option: `film_net_fp16.safetensors` → `INTERP_MODEL`) and `FrameInterpolate`
  (`interp_model`, `images`, `multiplier` INT 2–16 → `IMAGE`), both from
  `comfy_extras.nodes_frame_interpolation`. `FrameInterpolate` emits `(n − 1) × multiplier + 1`
  frames, so the correct output rate is `base_fps × multiplier`.
- `RIFEInterpolation` is `custom_nodes.ComfyUI-VFI`, resampling `source_fps` → `target_fps`.
  The templates drive it from the `MS_INPUT_BASE_FPS` (24) and `MS_INPUT_INTERP_FPS` (60)
  primitives.
- VideoHelperSuite's `combine_video` writes the first frame as a PNG beside the video and
  fills its metadata from two hidden inputs: `prompt` and `extra_pnginfo`. It calls
  `metadata.add_text(x, json.dumps(extra_pnginfo[x]))` for every key. ComfyUI's frontend sends
  `extra_data.extra_pnginfo.workflow`; `ComfyClient.queue` sends only `{"prompt", "client_id"}`.
  **That is the whole of defect 2**: with no `extra_pnginfo`, the PNG has a `prompt` chunk and
  no `workflow` chunk, and a `prompt`-only image is exactly what "dragging an API file" looks
  like.
- Node ids 166 and 167 are free in all three templates.

## Design

### 1. `h3lab/comfy/editor.py` — the editor-format projection

One new module with one public function:

```python
def to_editor_workflow(
    workflow: dict[str, Any],
    prompt: Prompt,
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]
```

It takes the **template** (for node metadata: position, size, title, colour, slot types,
groups, `extra`) and the **patched API prompt** (for truth: which nodes survived, what they
are wired to, what every widget is set to) and returns an editor-format workflow.

The load-bearing decision: this is a **projection of `apply_config`'s output, never a second
implementation of its rules.** The lab already knows how to turn a config into a graph; a
parallel "apply the config to the editor graph" would be two authorities that drift, and the
first divergence would be invisible — an exported graph that runs differently from the run it
claims to describe. So `apply_config` stays the only place that decides anything, and
`editor.py` only changes the *notation*.

How it works, per node in the prompt:

- Start from the template node with that id; synthesise a minimal node if the template has
  none (the reference loaders `apply_config` can create for a run with more references than
  the template drew).
- Every input slot's `link` is set from the prompt: a `[source, slot]` value becomes a new
  link, anything else becomes `null`. An input the prompt links but the template never drew
  is appended as a new slot.
- Every literal input is written into `widgets_values` at the position `nodes.WIDGET_ORDER`
  gives it (or by key, for `VHS_VideoCombine`'s dict-shaped widgets).
- Nodes the prompt does not contain are **removed, not bypassed**. A bypassed node whose links
  were rewired is a graph that lies about what it would do if you re-enabled it. Groups stay,
  because they are boxes and they carry the template's reading structure.
- `Note` and `MarkdownNote` survive (they are commentary and have no links). The rgthree
  bypassers do not: a switch that toggles nodes which are no longer there is worse than no
  switch.

The correctness property, and the test that pins it:
**`to_api_prompt(to_editor_workflow(template, prompt)) == prompt`.**
Round-tripping through the lab's own importer is the only assertion that can catch a widget
written to the wrong index or a link pointing at the wrong slot.

`provenance` is written to `extra["h3lab"]` — run id, label, config hash. It rides along in
the PNG too, so an image dragged back in can be traced to the run that made it.

### 2. Export the workflow

- `Lab.workflow_for_run(run_id) -> dict` — load the template for the run's mode, apply the
  run's stored config with the run's id as the output tag, project it, attach provenance.
- `GET /api/runs/{run_id}/workflow` — the graph as `application/json` with a
  `Content-Disposition: attachment` filename of `h3lab-<seq>-<run id>.json`. A missing run is
  the existing 404 Problem; an unpatchable template is the existing 422 `workflow` Problem.
- The Run page gains a **Download workflow** action beside the existing run actions.

The export merges the run's stored config with the template **as it is on disk now**. If a
template has been edited since the run, the export reflects the edit. That is the honest
behaviour — the alternative is storing a copy of the graph per run, which is a database of
duplicated JSON to answer a question nobody has asked yet — and the README says so plainly.

### 3. The saved image carries the editor graph

`ComfyClient.queue` and `.execute` take an optional `workflow` argument and, when given, post
`extra_data: {"extra_pnginfo": {"workflow": workflow}}` alongside the prompt. The runner
builds the projection from the same prompt it is submitting and passes it.

Consequences, all of them wanted: the PNG beside the video gains a `workflow` chunk, so
dragging it into ComfyUI restores the laid-out graph; the mp4's metadata gains the same
(VHS writes `video_metadata` from the same dict); and the file the export endpoint hands you
is byte-identical to the graph in the image, because both come from one function.

### 4. Frame interpolation: off, FILM, RIFE

**Domain.** `GenerationConfig.rife: bool` becomes:

```python
Interp = Literal["off", "film", "rife"]
interp: Interp = "off"
```

`rife` survives as a **legacy input alias only**: a `mode="before"` validator maps
`{"rife": true}` to `interp="rife"` and `{"rife": false}` to `interp="off"`, and an explicit
`interp` always wins over the alias. It exists for stored rows and for the old benchmark's
import; it is not part of the vocabulary any more, and `CONTEXT.md` says so.

Everything that named the boolean follows: `HASHED_FIELDS`, `FIELD_LABELS` ("Interpolation"),
`derive_label`, `arena.HELD_FIELDS` (interpolation is still *held* — it flatters a clip
without improving the generation, so a voter who can see it is answering a different
question), `arena.pool_label` ("film" / "rife" / "no interp"), and the insights axis (now
`categorical`).

**Graph.** `_wire_video_path` picks one interpolator or none:

| `interp` | Chain | Frame rate |
| --- | --- | --- |
| `off` | decode → [upscale] → combine | `MS_INPUT_BASE_FPS` (24) |
| `film` | decode → **FrameInterpolate** → [upscale] → combine | base × 2 (48) |
| `rife` | decode → **RIFEInterpolation** → [upscale] → combine | `MS_INPUT_INTERP_FPS` (60) |

The FILM multiplier is fixed at 2 — the node's own minimum, and "double the frame rate" is
exactly what the setting has always promised. It is not a config field: it would be a hashed
value that means nothing for two of the three options, and nobody has asked to triple a
frame rate. The loader's `model_name` is left at the template's value for the same reason the
GGUF text encoder is: which interpolation checkpoint to load is knowledge the lab does not
have and should not invent.

**Templates.** All three gain, inside the group renamed from "RIFE Frame Interpolation" to
"Frame Interpolation" and bypassed by default like every other optional group:

- `166` `FrameInterpolationModelLoader`, `widgets_values: ["film_net_fp16.safetensors"]`
- `167` `FrameInterpolate`, `widgets_values: [2]`, `interp_model` ← 166, `images` ← 125
  (`VAEDecode`)

167's output is left unconnected in the template. Both RIFE and FILM want to feed the same
downstream input, and litegraph allows one link per input, so the template cannot draw both;
the lab wires the winner per run, and the group's note says so.

### 5. Migration v2 — the hashes have to move with the name

`interp` is in `HASHED_FIELDS`, so the canonical form of every config changes and so does
every hash derived from it. Stored `config_hash` and `recipe_hash` would keep their old
values while new runs got new ones: duplicate detection and recipe grouping would silently
split at the rename, with no error anywhere.

So migration v2 rewrites, per row of `runs` and `presets`: parse `config_json`, revalidate it
through the model (which applies the alias), write it back in today's vocabulary, and
recompute `config_hash` and `recipe_hash` for runs. A row whose config cannot be parsed is
left exactly as it was — a benchmark result must never be lost to a migration.

This needs a Python step, which the SQL-only migration runner cannot express, so `Migration`
gains an optional `fn(conn)` that runs after its SQL.

### 6. Front end

- The Lab form's RIFE switch becomes an **Off / FILM Net / RIFE** segmented control, built
  from the `ToggleGroup` already used for mode and preset levels. The hint states the frame
  rate each option produces, because "what does this cost me" is the question a benchmarking
  user is asking: *"Off keeps 24 fps. FILM Net doubles it to 48. RIFE resamples to 60."*
- `GET /api/meta` grows `interpolations` and `interpolation_labels`, so the browser never
  invents the vocabulary (and never renders `rife` as "Rife").
- The sweep builder offers the three values on that axis.
- The Run page gains the download action.

## Success criteria

1. `GET /api/runs/{id}/workflow` returns an editor-format graph that ComfyUI loads with the
   template's layout, and whose settings are the run's.
2. `to_api_prompt(export) == the prompt that ran`, asserted in the test suite.
3. The PNG saved beside a new run's video contains a `workflow` chunk in editor format,
   proved against a real generation.
4. `interp` accepts `off`, `film`, `rife`; each produces a video at 24, 48 and 60 fps
   respectively, proved by three real generations on the live ComfyUI.
5. A database written before the rename opens with its configs and hashes migrated, and its
   runs still group with new ones.
6. `pytest`, `npm test`, `npm run typecheck`, `npm run build`, and `tests/test_contract.py`
   are green.

## Out of scope

Exporting a draft config from the Lab page (the request names a *run*); a catalog of
interpolation checkpoints; a configurable FILM multiplier; storing a per-run copy of the
graph.
