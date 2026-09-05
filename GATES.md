# Gates: Benchmark configuration-to-execution parity

OWNS: h3lab/**, tests/**, scripts/**, web/src/**, minimax_h3_unified_guided_dual.json

Scope: Sweep-selected values must reach the queued ComfyUI prompt, and stored run configuration must agree with actual execution for every managed parameter.

- [x] G0: this ledger states executable outcomes that can fail
  CHECK: node /home/kadobot/.agents/skills/unlazy/scripts/gate-lint.mjs GATES.md
  EXPECT: LINT OK
  EVIDENCE: LINT OK

- [x] G1: the reported recent step-sweep mismatch is reproduced and traced to the exact boundary that replaced the selected values
  CHECK: .venv/bin/python scripts/audit_recent_execution.py --expect-mismatch steps
  EXPECT: RECENT_STEPS_MISMATCH_REPRODUCED
  EVIDENCE: runs #10 and #11 reached Studio with 26/28 steps, then SplitSigmas(step=4) truncated both; Spectrum's two-pass progress originally reported 8 work units and the repaired schedule metric reports 4

- [x] G2: every sweepable generation parameter retains its selected value through expansion and workflow preparation
  CHECK: .venv/bin/python -m pytest tests/test_execution_parity.py -q && printf '\nOFFLINE_PARITY_OK\n'
  EXPECT: OFFLINE_PARITY_OK
  EVIDENCE: 17 focused parity tests passed; 24 representative configs, including every installed model and graph-level feature, also passed live ComfyUI schema validation

- [x] G3: a live two-arm benchmark records and executes 20 and 28 sampler steps respectively
  CHECK: .venv/bin/python scripts/verify_live_execution_parity.py --steps 20 28
  EXPECT: LIVE_STEPS_PARITY_OK
  EVIDENCE: runs #23 and #24 persisted configured/observed step pairs 20/20 and 28/28; LIVE_STEPS_PARITY_OK

- [x] G4: the complete backend regression suite passes
  CHECK: .venv/bin/python -m pytest tests -q && printf '\nBACKEND_REGRESSION_OK\n'
  EXPECT: BACKEND_REGRESSION_OK
  EVIDENCE: 769 passed in 74.21s

- [x] G5: the complete frontend suite, lint, and production build pass
  CHECK: npm run test -- --run && npm run lint && npm run build && printf '\nFRONTEND_REGRESSION_OK\n'
  EXPECT: FRONTEND_REGRESSION_OK
  CWD: web
  EVIDENCE: 147 tests passed; eslint passed; Vite production build passed

- [x] G6: the persisted stack workflow has no primary SplitSigmas truncation
  CHECK: /home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests -q
  EXPECT: 33 passed
  CWD: /home/kadobot/Projects/comfyui-minimax-h3-stack
  EVIDENCE: 33 passed in 0.04s

- [x] G7: internal cache work cannot multiply the run page's sampler-step count or seconds-per-configured-step denominator
  CHECK: .venv/bin/python -m pytest tests/test_comfy_progress.py -q
  EXPECT: 30 passed
  EVIDENCE: live Spectrum runs #15 and #16 persisted configured/execution steps as 20/20 and 21/21; internal capture/replay progress was normalized to each sigma schedule

- [x] G8: restarting the service cannot reconcile a run after the worker has already claimed it
  CHECK: .venv/bin/python -m pytest tests/test_api.py::test_startup_does_not_reconcile_after_the_worker_is_running -q
  EXPECT: 1 passed
  EVIDENCE: after the fully updated service restarted, queued run #17 remained running rather than being marked interrupted

- [x] G9: historical run pages no longer retain doubled wrapper work as their execution-step metric
  CHECK: .venv/bin/python scripts/repair_execution_metrics.py
  EXPECT: EXECUTION_METRICS_WOULD_REPAIR count=0
  EVIDENCE: seven affected rows repaired; a second dry run found zero remaining corrections

- [x] G10: every packaged Studio template disables Spectrum when its selected sampler cannot execute Spectrum forecasting
  CHECK: /home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests/test_studio_templates.py -q && printf '\nTEMPLATE_CACHE_COMPATIBILITY_OK\n'
  EXPECT: TEMPLATE_CACHE_COMPATIBILITY_OK
  CWD: /home/kadobot/Projects/comfyui-minimax-h3-stack
  EVIDENCE: 18 tests passed; both live Studio and h3-bench manifests expose 83 templates and zero incompatible cache/sampler combinations

- [x] G11: h3-bench refuses a manually composed Spectrum and unsupported-sampler run before ComfyUI is asked
  CHECK: .venv/bin/python -m pytest tests/test_engine.py -k spectrum_sampler -q && printf '\nMANUAL_CACHE_COMPATIBILITY_OK\n'
  EXPECT: MANUAL_CACHE_COMPATIBILITY_OK
  EVIDENCE: 4 focused cases passed; run 20's original settings now dry-run fail before submission with the stochastic ER-SDE incompatibility

- [x] G12: de-rope keeps its internal pass-one audio source while benchmark output remains video-only
  CHECK: .venv/bin/python -m pytest tests/test_execution_parity.py -k derope -q && printf '\nDEROPE_AUDIO_PARITY_OK\n'
  EXPECT: DEROPE_AUDIO_PARITY_OK
  EVIDENCE: focused parity test passed; corrected run 20 graph validated with VAEDecodeAudio feeding H3AudioSmear and no final mux audio

- [x] G13: a live corrected variant of failed run 20 completes with ER-SDE, de-rope, and no incompatible Spectrum cache
  CHECK: .venv/bin/python scripts/verify_run20_recovery.py
  EXPECT: RUN20_RECOVERY_OK
  EVIDENCE: live run 25 succeeded in 591.16s with configured/observed steps 28/28, ER-SDE and de-rope enabled, Spectrum disabled, and a saved video artifact

- [x] G14: run 27 is reproduced as a 28-step guided primary pass replaced by a hidden four-step unguided final pass
  CHECK: .venv/bin/python scripts/verify_run27_derope.py --audit-only
  EXPECT: RUN27_REGRESSION_REPRODUCED
  EVIDENCE: run 27's original prompt had Studio steps=28 but H3InjectSchedule total_steps=6 and inject=0.7 (four executed steps), fed BasicGuider directly from references-only conditioning, and saved H3ExactRecover; runs 25 and 27 are byte-identical with SHA-256 5229df7835a1cb098f384a264112422ad6669b1bd3defdd80fabc64499dfe304; a prompt-derived regression record keeps the audit repeatable after ComfyUI history rotation

- [x] G15: Studio remaps every guide onto the first held frame retained by exact recovery
  CHECK: /home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests/test_guide_mapping.py -q && printf '\nDEROPE_GUIDE_REMAP_OK\n'
  EXPECT: DEROPE_GUIDE_REMAP_OK
  CWD: /home/kadobot/Projects/comfyui-minimax-h3-stack
  EVIDENCE: 7 tests passed; each world-frame guide maps to the first repeated frame in the hold map, target/world bounds are clamped, and malformed maps fail with guide-remapping context

- [x] G16: the persisted and flattened de-rope pass inherits Studio guides, seed, scheduler, sampler, ER-SDE parameters, and effective steps
  CHECK: .venv/bin/python -m pytest /home/kadobot/Projects/comfyui-minimax-h3-stack/tests/test_workflow.py -q && .venv/bin/python -m pytest tests/test_execution_parity.py -k derope -q && printf '\nDEROPE_FINAL_PASS_PARITY_OK\n'
  EXPECT: DEROPE_FINAL_PASS_PARITY_OK
  EVIDENCE: 2 persisted-workflow tests and 2 flattened-prompt tests passed; the final pass inherits Studio seed, scheduler, total steps, ordinary/ER-SDE sampler choice and all ER-SDE parameters, uses inject=0.50, re-anchors Studio guides with the smear hold map, and anchors them against the combined H3V2VInit AV latent

- [x] G17: the canonical, benchmark, and installed unified workflows are semantically identical
  CHECK: .venv/bin/python scripts/verify_run27_derope.py --check-workflows
  EXPECT: DEROPE_WORKFLOWS_IN_SYNC
  EVIDENCE: DEROPE_WORKFLOWS_IN_SYNC after synchronizing the stack source, h3-bench copy, and installed user/default workflow

- [x] G18: one live same-seed prompt saves run 27's primary and repaired de-rope outputs for comparison
  CHECK: .venv/bin/python scripts/verify_run27_derope.py
  EXPECT: RUN27_DEROPE_PARITY_OK
  EVIDENCE: prompt 6ec27984-e0c8-49f5-b105-47c0ec1235a6 completed in 959.934s with a 28-step primary and 14-step final pass; both saved videos are 960x544, 24 fps, and 124 frames at results/verification/run27/{primary,derope}.mp4; paired strips retain the same five in-range battle anchors, both late guides clamp to the final world frame, and final-versus-primary SSIM is 0.710786

- [x] G19: both affected repositories pass their complete regression suites
  CHECK: .venv/bin/python -m pytest tests -q && /home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest /home/kadobot/Projects/comfyui-minimax-h3-stack/tests -q && printf '\nDEROPE_REGRESSION_OK\n'
  EXPECT: DEROPE_REGRESSION_OK
  EVIDENCE: h3-bench 769 passed in 74.21s; stack 33 passed in 0.04s; Ruff checks passed on every touched Python file

- [x] G20: a Template-axis Current settings arm normalizes incompatible Spectrum before the run is stored
  CHECK: .venv/bin/python -m pytest tests/test_api.py::test_current_template_sweep_queues_a_normalized_spectrum_er_sde_config -q
  EXPECT: 1 passed
  EVIDENCE: runs #89-#92 reproduced the worker-time rejection; the deployed sweep preview now resolves the same Current settings payload to cache=none before hashing or queueing, corrected variants #137-#140 are queued with Spectrum disabled, and #137 passes a live graph dry run
