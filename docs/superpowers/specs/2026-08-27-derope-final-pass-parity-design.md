# De-rope final-pass parity

## Problem

Run 27 completed its configured 28-step primary pass, then replaced that result
with a four-step de-rope pass. The final pass used a fixed six-step schedule at
0.70 injection, seed 0, the beta scheduler, a generic ER-SDE sampler, and
references-only conditioning. It therefore ignored Studio's step count, seed,
scheduler, selected sampler and ER-SDE parameters, and all seven timed guides.

This was deterministic rather than a transient execution failure: runs 25 and
27 had identical generation settings and byte-identical final videos.

## Required behavior

- De-rope remains opt-in and does not alter the ordinary output path.
- Its final pass inherits Studio's effective step count, resolved seed,
  scheduler, and active sampler, including configured ER-SDE parameters.
- Its partial-denoise injection is 0.50, the fidelity-oriented operating point
  documented by `H3InjectSchedule`.
- Timed image and audio guides are re-anchored to the stretched latent. A guide
  on original frame `i` moves to the first frame of that frame's hold group:
  `sum(holds[:i])`. This is the frame retained by `H3ExactRecover`.
- Explicit guide frame indices retain precedence over guide times, matching
  existing Studio behavior. Inputs are clamped to the original world length
  before remapping.
- The saved video continues to come from the recovered de-rope result when
  de-rope is enabled.
- Benchmark metrics continue to report the configured primary schedule as
  established by the existing progress contract; tests separately verify the
  final pass's derived partial schedule.

## Ownership and data flow

`MiniMaxH3AnchorGuides` owns guide placement. It receives an optional H3 hold
map and remaps guide frames before calling the existing guide-anchoring path.
Existing callers that omit the hold map retain their current behavior.

The persisted unified workflow feeds the de-rope branch with:

1. Studio's references-only conditioning;
2. the VAE-encoded smeared latent;
3. Studio's original guide list;
4. `H3TimeSmear`'s stretched length and hold map;
5. the existing video and audio VAEs.

The resulting conditioning drives the second guider. The second
`SamplerCustomAdvanced` receives Studio's resolved seed and the same active
sampler as the primary pass. `H3InjectSchedule` receives Studio's scheduler and
effective step count, with injection set to 0.50.

The stack workflow is the canonical persisted copy. The installed ComfyUI and
h3-bench workflow copies must remain synchronized with it.

## Compatibility and failure behavior

The new hold-map input is optional, so existing upscaling and standalone
`MiniMaxH3AnchorGuides` workflows are unchanged. Invalid hold-map JSON or a map
that cannot cover the original guide frame fails at the anchoring boundary with
guide-remapping context rather than silently dropping the guides.

Templates may continue to select de-rope with any supported Studio sampler
because the second pass no longer substitutes an unrelated sampler. The
existing Spectrum compatibility policy remains unchanged.

## Verification

- Unit tests prove frame- and time-based guide remapping, clamping, unchanged
  behavior without a hold map, and malformed-map failure.
- Workflow tests prove that pass 2 inherits seed, scheduler, active sampler,
  ER-SDE parameters, and steps, uses 0.50 injection, and consumes re-anchored
  guides.
- Execution-parity tests prove the non-de-rope path is unchanged and contains
  no dangling links.
- Canonical, installed, and benchmark workflow copies are compared after the
  update.
- Full stack and h3-bench regression suites run.
- A live same-seed reproduction based on run 27 captures both the 28-step
  primary output and the recovered final output from one prompt. The result is
  accepted only after confirming that all seven guide entries reach pass 2
  (including the two out-of-range entries that existing Studio behavior clamps
  to the final frame), the five in-range shot anchors remain recognizable, and
  the final output is a refinement of the primary scene rather than a different
  four-step generation.
