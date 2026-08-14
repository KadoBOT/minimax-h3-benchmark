# Workflow Resilience and the Turbo LoRA Axis — Design

**Date:** 2026-08-11
**Status:** Approved (one-shot: self-approved after spec self-review)
**Surface map:** `2026-08-11-workflow-resilience-surfaces.md`
**Phases:** `2026-08-11-workflow-resilience-phases.md`
**Plan:** `../plans/2026-08-11-workflow-resilience.md`

## The problem, measured

The user edits the ComfyUI workflow templates constantly. The three files in the repository root
are already a new export, and against them the current code fails **102 of 506 backend tests**;
the first failure reads `WorkflowError: the workflow has no diffusion model loader (node 1)`.

Four independent breakages, each fatal on its own:

1. **Subgraphs.** The new exports wrap the whole pipeline in a ComfyUI subgraph. The top level
   holds 5–23 boxes and one instance node whose `type` is a UUID; the 51–54 real nodes live in
   `definitions.subgraphs[0].nodes`, whose links are *objects* (`{origin_id, origin_slot, …}`)
   rather than the arrays the top level uses. `to_api_prompt` walks `workflow["nodes"]` only, so
   it produced a five-node prompt with no model in it.
2. **Renumbering.** The reference loaders moved from ids 200–240 to 20 and 400–422 — and ids
   200–205 are now a colour-grade chain (HDR → LUT → colour correct → glow → sharpen). The lab
   drops "unused reference nodes" by id, so an flf2v run would have deleted the user's grade and
   left the muxer with no images.
3. **Widget drift.** Four classes changed their widget lists under the lab's static table:
   `MiniMaxH3TurboLoRA.strength_model` became `strength` and gained `low_vram`; `SolAttnPatch`
   inserted `int8_pv` *in the middle* of its list, which silently shifts every value after it;
   `SpectrumApplyMiniMaxH3` gained four; `RTXVideoSuperResolution` became a dynamic combo.
   Thirteen further classes in the templates (the grade chain, `Seed (rgthree)`, three new
   attention patches, `ModelPreviewOverrideKJ`, `SaveImage`, …) have no entry in that table at
   all, so their widget values are dropped on the way to the prompt.
4. **Chain order.** The model chain is no longer `loader → turbo → sol → sage → shift → cache`.
   It is `loader → turbo → extra LoRA → sage → memory-efficient sage → sol → shift → spectrum →
   easy → h3 → low-VRAM → chunked FFN → preview override → scheduler/guider`. The lab asserted
   its own order and rejected anything else.

The common cause is not any one of these. It is that **the lab holds a copy of the template's
structure in Python** — ids, widget names, chain order — and a copy goes stale every time the
original is edited.

The second ask, "change the MiniMax-H3 Turbo LoRA and test different LoRAs in the benchmark
matrix", is a smaller feature that lands on the same code: `turbo` is a boolean, and the LoRA
filename is whatever the template happens to have saved. On this machine that is
`Flux_2-Turbo-LoRA_comfyui.safetensors` — a Flux LoRA, in an H3 graph — which is what "the
template happens to have saved" is worth.

## Approaches considered

**1 — Re-pin the constants.** Renumber `nodes.py`, add the missing widget orders, reorder the
chain. Half a day, and the next export breaks it again in exactly the same way. Rejected as the
answer; kept as the bottom layer of the role resolver, so the two `_`-prefixed backups of the old
templates still load.

**2 — Let ComfyUI's frontend compile the template.** `app.graphToPrompt()` is the authority on
what a workflow means; drive it headless (the repo already drives ComfyUI's canvas from
`web/scripts/comfy-drop.mjs`), cache the compiled prompt per template mtime. Highest fidelity —
subgraphs, dynamic combos, reroutes and bypass all come free. Rejected as the runtime path: it
makes Node, Playwright and a live ComfyUI hard dependencies of queueing a run, a cold cache
blocks the queue while ComfyUI is busy, and it does not remove any of the role work, because a
compiled prompt still has to be patched per run. Adopted as a **verification** tool instead.

**3 — Read the graph instead of assuming it. (Chosen.)** Replace each copied assumption with an
observation, in four modules with one job each:

| Module | Replaces the assumption that… | With |
| --- | --- | --- |
| `workflow.py` | the graph is a flat `nodes` array | a reader that flattens subgraph definitions to ComfyUI's own execution ids (`169:1`), resolves boundary links and promoted widgets, and keeps slot types, bypass state, titles and layout |
| `schema.py` | widget names are known at authoring time | the live `/object_info`, with dynamic-combo expansion, cached, falling back to the node's own declared inputs and then a static table |
| `roles.py` | node 1 is the model loader | ~24 named roles resolved by title tag, class, graph edge, then legacy id — with a report of what resolved to what and why |
| `graph.py` | the chain is `loader → turbo → sol → …` | a live set and ComfyUI's own type-matched bypass rule, so the chain is whatever the template draws and a node the lab has never heard of survives in the position the user put it |

Trade-off accepted: four focused modules instead of two, and behaviour now depends on the
template's own bypass state. The second half of that is a feature — muting a group in ComfyUI is
how you turn it off in the lab too.

## Grill log

Every branch, the answer taken, and why. Facts were looked up rather than assumed; the sources
are named.

**Q1. What node ids does a prompt use once subgraphs are involved?** ComfyUI's own scheme, read
out of the shipped frontend bundle: `[...subgraphNodePath, node.id].join(":")`, so inner node 1
of instance 169 is `"169:1"`. Prompt keys are strings on the wire and opaque to `execution.py`,
so this is safe. Taking ComfyUI's scheme rather than inventing one means an error message about
node `169:1` means the same thing in the lab's log and in ComfyUI's.

**Q2. Trust `/object_info` for widget order, or the workflow's own `inputs` array?**
`/object_info` — it is the *installed* node's truth, and the workflow's copy is exactly the stale
snapshot this work is removing. Checked against the live instance: `RTXVideoSuperResolution`'s
saved `inputs` array lists `resize_type.width` / `resize_type.height`, while its saved
`widgets_values` are `["scale by multiplier", 2, "ULTRA"]` — the values only line up once the
dynamic combo is expanded for the *selected* option, which is what the frontend renders and what
`/object_info` describes. The node's declared inputs are the first fallback when ComfyUI is
unreachable, the static table the second, so the lab still builds a graph offline.

**Q3. What happens to a node the lab has no opinion about?** It keeps the template's own state:
active stays active, bypassed stays out. That is the whole answer to "survives workflow changes":
the user's colour grade, their memory-efficient attention patch and anything they add tomorrow
run because the lab does not have a list of nodes it approves of.

**Q4. How is a node removed without breaking the chain?** ComfyUI's own bypass rule: every
consumer of a removed node's output slot is re-pointed at that node's first input of the same
type, and dropped if there is none. This deletes `_wire_model_chain` entirely — the chain is not
rebuilt, it is *thinned* — and it is why the three new attention patches need no code.

**Q5. Bypass (mode 4) and mute (mode 2) — same treatment?** Yes, both mean "not in this run", and
both heal by pass-through. ComfyUI's mute is stricter (it starves consumers), but every muted node
in these templates is an optional branch whose consumers are pass-through positions anyway, and
treating them alike keeps one rule instead of two.

**Q6. Which nodes does the lab force on?** Only the ones the config names: the diffusion loader
for the chosen family, the turbo LoRA when turbo is on, the attention patch when Sol-Attn is on,
the one selected cache node, the chosen interpolator (and the FILM model loader with it), the
upscaler, the two VRAM cleaners, and the media loaders the mode uses. Everything else is Q3.

**Q7. The audio branch?** Still force-*off*, for the reason already in the code: MiniMax audio
latents frequently contain NaN or +Inf, and the AAC mux then fails after the picture track is
written, losing the file. A benchmark needs the picture track. `SaveAudio` then has no `audio`
input and is dropped by the general "an output node missing a required input cannot be a graph
root" rule, which replaces the old three-class table.

**Q8. Keep `EDITOR_ONLY_NODES`?** No — delete it. Once the prompt is pruned to what the outputs
actually depend on, the rgthree bypassers, the step switch, the fps switch and the primitives
behind them fall out because nothing reachable needs them. A hand-maintained list of nodes to
delete is the same kind of stale copy as a hand-maintained list of ids.

**Q9. Then how is the muxer's frame rate decided, if the fps switch is pruned?** The lab writes
the literal, as it does today, but reads the numbers out of the template instead of holding
constants: the base rate is resolved by following the video node's `frame_rate` input through
switches and primitives to a value; RIFE's target comes from `RIFEInterpolation.target_fps` the
same way; FILM multiplies the base by `FrameInterpolate.multiplier`. A template that changes 24 to
30 changes the lab's answer with no code edit. The rule that made this necessary is unchanged:
FILM multiplies frames without being told a rate, so a muxer left at the base rate writes a valid
file that plays at half speed.

**Q10. How are the r2v reference loaders found now that they are not at 200+?** By the slot they
feed. The conditioning node declares `ref_images.ref_image_0…8`, `ref_videos.…`,
`ref_video_audios.…`, `ref_audios.…`; the lab walks upstream from slot *i* through fit and
component nodes to the loader with a file widget, and writes the config's *i*-th filename there.
Slots the config does not use lose their input, and the loader behind them becomes unreachable and
is pruned. When the config asks for more references than the template wired, a loader is minted
(as today), with an id above every id in the graph.

**Q11. Does the export keep the subgraph nesting?** No. It projects to a **flat** positioned
editor graph: every node the run used, at the position the template drew it, with its title,
colour, group and notes, and the subgraph's own nodes translated below the parent so nothing
overlaps. Reconstructing subgraph boundaries would mean re-minting promoted input slots for links
the lab re-pointed, which is the most bug-prone code in the whole change and whose failure mode is
a file ComfyUI refuses to open. A flat graph is also the more honest artifact: an export is a
snapshot of one run, and "what actually ran" is exactly what you want to read without opening a
subgraph. The round-trip property therefore weakens from equality to equality-up-to-id-renaming,
and the test says so explicitly.

**Q12. Scope of the LoRA feature: one turbo LoRA, or a LoRA stack?** One. `turbo_lora` and
`turbo_lora_strength` join `turbo`, and the template's *optional* LoRA slot stays the template's
business. Reason: the arena only ranks settings that change how the pixels were sampled while
holding what is being generated. A turbo LoRA is a speed/quality trade — contested, sweepable, the
thing the user asked to matrix. A style LoRA changes the subject, which makes two runs
incomparable, so it would have to be a *held* field, and mixing both in one release muddies the
one classification the arena depends on. Recorded under "deliberately undone".

**Q13. What does an empty `turbo_lora` mean?** The same as an empty `diffusion_model`: the lab's
default filename. The catalog fills the form with a LoRA the running ComfyUI actually offers, so a
queued run always records the file it used. Preflight additionally rejects a name ComfyUI does not
list, which is cheaper than finding out after a model load.

**Q14. Does `low_vram` become a setting?** No. It trades peak VRAM for a softer merge on
quantised bases — a property of the machine, not a benchmark question, and the node's own tooltip
says to turn it on only when you OOM. It stays the template's value.

**Q15. Two new hashed fields — migration or not?** Migration. `canonical_form` gains two keys, so
every stored `config_hash` and `recipe_hash` stops matching what the model computes, which would
silently break duplicate detection and recipe grouping. Migration `v3` rewrites each stored config
through the model and recomputes both digests for `runs` and `presets`, exactly as `v2` did for
`interp`.

**Q16. Should a template edit still need a restart?** No. `WorkflowCache` reloads a file whose
size or mtime changed and announces it on the event bus. The original reason for caching — that
reloading per run made a mid-session edit change history — is satisfied by the export already
following the template on disk, and by the reload being announced rather than silent.

**Q17. How does the user find out a change broke something, without queueing a run?**
`h3lab check` grows a role table per template: which node each role resolved to, by which rule,
and which roles are missing. It also asks the live `/object_info` whether the built prompt is
submittable — unknown class, missing required input, unknown input name — which is the same
validation ComfyUI runs, three minutes of model loading earlier.

**Q18. What if a config needs a node the template does not have?** It fails with a sentence naming
the role and the mode, at dry-run time. Concretely: these templates dropped the GGUF loader, so a
`.gguf` model now answers "this template has no GGUF diffusion model loader" instead of quietly
loading the wrong file through `UNETLoader`.

## Design

### Reading a workflow — `h3lab/comfy/workflow.py`

`read(workflow, schema) -> Graph`, where a `Graph` is nodes keyed by execution id in template
reading order. Each node carries `class_type`, `title`, `mode`, `inputs` (a link `[source, slot]`
or a literal, by name), `input_types`, `output_types`, and its provenance: the instance `path`,
its `local_id`, and the template dict it came from (for the export).

Both link shapes are read: top-level arrays `[id, src, src_slot, dst, dst_slot, type]` and
subgraph objects `{id, origin_id, origin_slot, target_id, target_slot, type}`.

Subgraph flattening:

- a node whose `type` matches a `definitions.subgraphs[].id` is an instance; its inner nodes are
  read with `path + (instance_id,)` and ids joined with `:`. Nesting recurses.
- an inner link from the input node (negative id, `inputNode.id`) resolves to whatever the
  instance's matching input holds: an upstream link, or the literal from the instance's
  `widgets_values` when the input is widget-promoted (positional over the instance's inputs that
  carry a `widget` marker).
- an inner link into the output node records the inner producer, so consumers of the instance's
  output slot are re-pointed at it.

Widget values are folded into named inputs using the schema's widget order (links always win), with
`VHS_VideoCombine`'s dict-shaped `widgets_values` handled by key as today.

### Node schemas — `h3lab/comfy/schema.py`

`NodeSchema` per class: `widgets` (ordered names), `required`, `optional`, `types`, `output_node`.
Built from `/object_info` with two rules that matter:

- a `COMFY_DYNAMICCOMBO_V3` input expands, after its own value, into the nested inputs of the
  option that value selects — which is what the frontend renders and how `widgets_values` are
  positioned.
- link-only inputs (`MODEL`, `IMAGE`, …) are not widgets and take no position.

`Schemas` caches the whole `/object_info` for the process (it is ~2900 classes, one request),
degrades to the node's own declared inputs when ComfyUI is unreachable, and falls back to the
static table for the classes the lab has always known. `problems(prompt)` returns what ComfyUI's
validator would say: unknown class, missing required input, input the class does not declare.

### Roles — `h3lab/comfy/roles.py`

A role is a name for the part a node plays in the graph. Resolution, in order:

1. **Title tag** — `[h3lab:turbo_lora]` anywhere in a node's title, or one of the `MS_*` tags the
   templates already carry (`MS_INPUT_CONDITIONING`, `MS_CACHE_1_SPECTRUM`, `MS_OUTPUT_VIDEO`, …).
   This is the user's escape hatch: title a node and the lab finds it however the graph is rebuilt.
2. **Class** — a role's candidate classes, in preference order.
3. **Edge** — for the ambiguous ones: the CLIP loader is the source of the conditioning node's
   `clip`; the video VAE is the source of the decoder's `vae`; the audio VAE is the source of
   `audio_vae`; the base frame rate is what the video node's `frame_rate` resolves to.
4. **Legacy id** — the constants in `nodes.py`, accepted only when the class agrees too.

`resolve(graph) -> Roles` also answers `report()` — role, node id, rule, and the unresolved list —
which is what `h3lab check` prints and what the dry-run reports as a problem.

### Patching — `h3lab/comfy/graph.py`

`apply_config(workflow, config, *, output_tag, schema)`:

1. read the workflow, resolve roles;
2. compute the **live set**: every node the template has active, minus the roles this config turns
   off, plus the roles it turns on, plus loaders minted for references the template did not wire;
3. remove everything else with the type-matched pass-through rule;
4. write the config onto its roles: prompt text, seed, steps, sampler, scheduler, aspect,
   megapixels, duration, cache and attention widgets, the LoRA file and strength, the media
   filenames, the output prefix, and the muxer's frame rate;
5. prune to what the output nodes depend on, then drop any output node still missing a required
   input, repeating until stable;
6. return the prompt.

`WorkflowError` still names what is missing, now by role and mode rather than by node id.

### Export — `h3lab/comfy/editor.py`

`to_editor_workflow(workflow, prompt, *, schema, provenance)` projects the prompt back into a flat
editor graph: nodes in template reading order with their layout, titles, colours and flags; every
surviving inner node translated below the parent graph; groups and notes kept; links re-minted from
the prompt; ids renumbered to integers. The property under test becomes
`to_api_prompt(export) ≡ prompt` up to a bijection of node ids.

### The Turbo LoRA

`GenerationConfig` gains `turbo_lora: str = ""` and `turbo_lora_strength: float = 1.0`
(−10…10, the node's own bounds), both in `HASHED_FIELDS`, both **contested** in the arena, both
insight axes (categorical, numeric). `resolve_turbo_lora()` mirrors `resolve_model_filename()`.
`derive_label` and `loadout_label` name the LoRA's stem when turbo is on, so two rows in a sweep
read as different experiments rather than as duplicates.

The widget is written by name: `strength` when the installed node declares it, `strength_model`
when it declares that instead — the drift that broke this release cannot break it again.

The catalog gains `loras`, `turbo_loras` (the H3 ones), `loras_source`, and a `turbo_lora`
default, all from `MiniMaxH3TurboLoRA.lora_name`'s own combo options with `LoraLoaderModelOnly` as
the fallback. Preflight rejects a LoRA the running instance does not offer.

The Lab form puts the picker and the strength field under the Turbo toggle, both inert when turbo
is off. The sweep builder offers `turbo_lora` as an axis with the catalog's H3 LoRAs as values —
which is the "benchmark matrix" the request asks for: pick four LoRAs, expand, and the standings
rank them.

## Success criteria

1. `python -m pytest -q` green against the templates on disk (102 failures → 0).
2. A real generation on the live ComfyUI from each template, and one sweep of two different turbo
   LoRAs whose runs differ in the recorded config and in the graph submitted.
3. The colour-grade chain the user added is present in an flf2v run's prompt without the lab
   having been told it exists.
4. Deleting a node from a template, or renumbering it, changes nothing but the role report.
5. `h3lab check` names every role, every unresolved role, and every problem `/object_info` finds.
6. The exported workflow still opens in ComfyUI as a positioned graph, verified by dropping it on
   the real canvas.
7. `turbo_lora` is selectable in the Lab, sweepable as an axis, visible in compare and standings.

## Deliberately undone

- **The optional LoRA slot stays the template's.** Q12: a style LoRA is a held setting, not a
  contested one, and the arena's classification is worth more than the extra knob.
- **`low_vram` stays the template's.** Q14.
- **The export does not reconstruct subgraphs.** Q11.
- **No compiled-prompt cache driven by a headless browser.** Approach 2: it would make a browser a
  dependency of queueing a run.
