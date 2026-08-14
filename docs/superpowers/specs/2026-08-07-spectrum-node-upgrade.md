# Spectrum cache upgrade — surface map

The `ComfyUI-Spectrum-MiniMax-H3` node was upgraded. Its widget set and validation rules
changed, so the lab's preset tables and the saved workflow templates no longer match it.
Read the installed node rather than guessing: `comfyui_spectrum_h3/config.py` is the
authority for both the levels and the constraints.

## Ground truth, read from the installed node

`SpectrumH3Config` defaults and `validate()` (config.py), plus the node's own two presets:

| field | default / CONSERVATIVE | AGGRESSIVE | bounds |
| --- | --- | --- | --- |
| `blend_weight` | 0.50 | 0.75 | finite, 0..1 |
| `degree` | 1 | 4 | int >= 1 |
| `ridge_lambda` | 0.10 | 0.10 | finite, >= 0 |
| `window_size` | 2.0 | 2.0 | finite, >= 1 |
| `flex_window` | 0.75 | 3.0 | finite, >= 0 |
| `warmup_steps` | 1 | 5 | int >= 0 |
| `tail_actual_steps` | 1 | 1 | int >= 0 |
| `max_history` | 8 | 8 | int >= max(2, degree+1) |
| `history_storage` | `system_ram` | `system_ram` | `system_ram` \| `vram` |
| `debug` | False | False | bool |
| `bootstrap_first_forecast` | True | False | bool |

Cross-field rules, both raised from `validate()` on the GPU:

- `bootstrap_first_forecast` requires `degree == 1`
- `bootstrap_first_forecast` requires `warmup_steps <= 1`

The load-bearing surprise: aggressive raises `warmup_steps` to 5 rather than lowering it,
because a degree-4 fit needs more real points before it can forecast. The previous table
assumed the opposite and walked warmup 1/2/3 while leaving `degree` at 1.

## Surfaces

| surface | change | verification |
| --- | --- | --- |
| library/core — `h3lab/comfy/presets.py` `SPECTRUM` | rebuild the three levels on the node's own presets, moving `degree`/`flex_window`/`warmup_steps` together | unit: each level validates against the ported rules |
| library/core — `h3lab/comfy/presets.py` `H3` | `max_steps` is INT 1..10; the table sent 0.5/0.75 | unit: every table value is in range and the right type |
| library/core — `h3lab/comfy/presets.py` `EASY` | aggressive had a narrower window than moderate | unit: window widens monotonically with level |
| library/core — `h3lab/comfy/presets.py` validation | replace the silent `_honour_node_constraints` coercion with `cache_problems()` that reports | unit: an illegal custom combination is named, not rewritten |
| HTTP/API — `dry_run` / `preflight` | surface `cache_problems()` so an illegal combination fails in a second | unit: dry run reports the violation |
| infra/config — 3 workflow templates | `debug: true` -> `false`; `history_storage: 'vram'` -> `'system_ram'` | unit: template widgets equal node defaults for both fields |
| runtime — live GPU | all three levels actually sample | real generation per level, `sec_per_it` recorded |

## What the live run found that the plan did not

Running `scripts/live_cache_check.py` against the real GPU turned up three more faults, none
of which any unit test could have seen:

1. `graph.py` hardcoded `GGUF_CLIP_FILE = "MiniMax-Remover-Q8_0.gguf"` and wrote it over the
   template's `clip_name` on every quantised run. MiniMax-Remover is an object-removal
   model, not a text encoder, and it was not installed at all — so every `.gguf` model
   failed validation with `clip_name: Value not in list`. The template's own pairing is now
   left alone, because which encoder goes with which quantisation is not the lab's to guess.
2. `GenerationConfig.mp` accepted 0.05 while `ResolutionSelector` refuses anything under
   0.1, so those runs were submitted and rejected. The floor now lives in `preflight`.
3. Tightening that floor on the config field first — the obvious fix — made every stored run
   below it unparseable, and `runs.list()` raised on the whole table. A config model is also
   a storage format: its bounds may widen but must never narrow. Install-specific limits
   belong in preflight, which is checked before a run and never after.

Result, all nine levels sampling on an RTX 5090 at 4 steps and 0.1 MP:

| family | conservative | moderate | aggressive |
| --- | --- | --- | --- |
| spectrum | 4.57 s/it | 5.03 s/it | 5.03 s/it |
| easy | 5.02 s/it | 5.04 s/it | 2.28 s/it |
| h3 | 5.12 s/it | 7.34 s/it | 4.55 s/it |

The Spectrum levels are indistinguishable there because the probe runs 4 steps and the
stronger levels warm up for 3 and 5, so they never reach a forecast. That is a property of
the probe, not the presets — it proves each level is *runnable*, which is what it is for.
Comparing the levels needs a step count comfortably above the warmup.

## Why report rather than coerce

The previous fix derived `bootstrap_first_forecast` from `warmup_steps` so every preset
stayed runnable. That was right for the named levels but wrong as a general policy: a
custom combination that the node rejects is a mistake the user wants told about, and
silently rewriting a widget makes the recorded config differ from what actually ran —
which corrupts the benchmark comparison the lab exists to make. The named levels are now
legal by construction, so coercion has nothing left to do.
