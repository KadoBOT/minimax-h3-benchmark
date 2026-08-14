# Turbo Steps, Template Parity, and the Live Preview — Design

**Date:** 2026-08-11
**Surface map:** `2026-08-11-turbo-steps-and-live-preview-surfaces.md`
**Plan:** `../plans/2026-08-11-turbo-steps-and-live-preview.md`

## The problem, in the order it was found

A turbo run stores a step count it does not use. `GenerationConfig.effective_steps` reads the
schedule out of the LoRA's filename and that is what the sampler is given, but the `steps` field
keeps whatever it held when turbo was switched on — 8, for all 16 runs currently queued. That field
is hashed, contested in the arena, shown on the run page and shown in every config diff.

Three consequences, all of them live in this database right now:

1. Two turbo runs of the same LoRA that arrived with different leftovers are two experiments to the
   lab and one experiment to physics.
2. The run page prints `metrics.steps ?? config.steps`, so a queued turbo run advertises 8 when it
   will sample at 4.
3. Turning turbo off hands the leftover back as the run's real step count, which is how a bench
   whose normal is 20 quietly produced runs at 8.

The number the user saw during a render — `step n of 16` in the queue panel — is ComfyUI's own
progress `max`, which ticks more than once per sampler step on this model. They checked the render
and it was 8. That is ComfyUI's counter, and it is left alone.

The other two asks are independent: the FLF2V and T2V templates never received four model-chain
nodes that R2V has, one of which (`ModelPreviewOverrideKJ`) is what emits a preview image while the
sampler runs — and the lab's WebSocket listener throws every preview away unread.

## Decisions

### A — The step count follows the LoRA (chosen)

With turbo on, the validator sets `steps` to `turbo_steps_for(turbo_lora)`. This is the mirror of
the rule the config already applies in the other direction: with turbo off, `turbo_lora` and
`turbo_lora_strength` are cleared so every non-turbo run hashes alike. `effective_steps` keeps its
name and its meaning; it simply stops being able to disagree with the field beside it.

Considered and rejected:

- *Leave `steps` alone and drop it from the canonical form when turbo is on.* The identity would be
  right and everything a person reads would still be wrong, and `canonical_form`, the arena's
  contested-field partition and the insights axes would each need a conditional.
- *Only fix the display — show `effective_steps` everywhere.* It leaves the split identity, and it
  leaves the stored JSON saying a number the run never used, which is the thing the user asked to
  correct.

The cost of A is that turning turbo *off* on a config leaves the LoRA's count behind rather than
the count that was there before. A config is a value; it has no history to restore from. The place
a toggle actually happens is the browser, so the browser holds the memory: the form remembers the
count the draft had before turbo was switched on and puts it back when turbo goes off, falling back
to the lab's default of 20 when there is none. That is also the second half of the first ask —
after this, a turbo session cannot leave the bench running at 8.

### B — The 16 queued runs are corrected by a migration, not a script

`storage/migrations.py` already carries `_rehash_configs` and has run it twice (v2 for the `interp`
rename, v3 for the turbo LoRA fields). Re-parsing every stored config through the current model and
recomputing both digests is exactly what corrects a stale `steps`, for `runs` and `presets`, on
every database that ever opens this code — not just the one on this machine. No run is deleted, no
row changes status, and the labels do not move because `derive_label` already used
`effective_steps`.

### C — The preview travels as a counter, and the image is fetched

`run.progress` grows one integer, `preview_seq`. The newest frame is held in memory by the runner,
for the active run only, and served from `GET /api/runs/{id}/preview` as `image/jpeg`.

Where the frame comes from was found to be the opposite of the assumption above: the override node
does not use ComfyUI's binary preview channel at all. It draws the latent itself — through the tiny
VAE the templates name, so the picture is true RGB rather than a latent smear — and sends a
`kj_preview_override` JSON message with the JPEG base64 inside, to the client that queued the
prompt. It also patches ComfyUI's own previewer off while it samples, so on these templates no
binary frame is ever sent. Both channels are read; only one of them speaks here.

Considered and rejected:

- *Base64 the frame into the SSE event.* The event bus keeps a replay buffer that a reconnecting
  browser asks to be replayed; progress is published up to three times a second. That is megabytes
  of stale JPEG in a ring buffer designed for state changes.
- *Relay ComfyUI's WebSocket to the browser.* Two sockets, a second origin, and the lab stops being
  the only thing that knows which run a frame belongs to.

A preview is a progress indicator, not an artifact: it is never written to disk, and it is dropped
when the run finishes. The artifact of a run is still the video, its poster and its filmstrip.

### D — Only the four new nodes travel to the other templates

FLF2V and T2V gain `MiniMaxH3MemoryEfficientSageAttentionPatch`, `MiniMaxLowVRAMAttention`,
`MiniMaxChunkFeedForward` and `ModelPreviewOverrideKJ`, wired in R2V's order, each with R2V's own
widget values.

Nothing already in those templates is touched — in particular not `PathchSageAttentionKJ`, which
R2V has pinned to `sageattn_qk_int8_pv_fp8_cuda++` while the others run `auto`. That value is not a
hashed field, so changing it would move the numbers of every future FLF2V and T2V run without
moving a single config hash, and the 149 runs already recorded would silently stop being
comparable with the next one. If that backend is wanted on the other two templates it is its own
change, with its own before-and-after.

The edit is made by a throwaway script rather than by hand, and both files are re-read through
`h3lab.comfy.workflow` afterwards so the chain is asserted rather than eyeballed.

## Success criteria

- A queued turbo run's stored `steps` equals what its sampler is given, and two turbo configs that
  differ only in a leftover step count hash alike.
- The 16 runs queued on this machine are corrected in place; none is deleted, none changes status,
  and the queue still runs.
- Turning turbo off in the browser restores the step count the draft had before, or 20.
- FLF2V and T2V build prompts containing the four new classes, every role still resolves, and the
  installed ComfyUI objects to nothing in either template.
- While a run is rendering, the queue panel shows the frame ComfyUI is previewing, and shows
  nothing at all when the template has no preview override.
