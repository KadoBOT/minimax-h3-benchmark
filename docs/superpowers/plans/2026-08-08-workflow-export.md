# Workflow Export and Frame Interpolation Implementation Plan

> **For agentic workers:** Execute inline, task by task (this repository's owner has ruled out
> subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export any run as a loadable ComfyUI *editor* workflow, embed that same graph in the
image ComfyUI saves beside the video, and turn the RIFE boolean into a three-way frame
interpolation setting (off / FILM Net / RIFE).

**Architecture:** `apply_config` remains the only thing that decides what a run's graph is. A
new `h3lab/comfy/editor.py` projects its output back into the editor's node/link notation
using the template for layout. That one function serves both the export endpoint and the
`extra_data.extra_pnginfo.workflow` the runner now submits, so the downloaded file and the
graph inside the PNG are the same bytes.

**Tech Stack:** Python 3.11+, FastAPI, pydantic v2, SQLite; React 19 + TypeScript + Tailwind
v4 + Base UI; pytest, vitest; a live ComfyUI 0.30.0 at `127.0.0.1:8188`.

## Global Constraints

- Vocabulary is `CONTEXT.md`'s. The new term is **frame interpolation**, field `interp`,
  values `off` / `film` / `rife`. No synonyms in code, on the wire, or in the UI.
- `rife` remains accepted as an input alias for stored data only; an explicit `interp` wins.
- The exported graph is a projection of `apply_config`'s output. No second implementation of
  the wiring rules.
- FILM multiplier is fixed at `2`. Frame rate: off → base (24), film → base × 2 (48),
  rife → `MS_INPUT_INTERP_FPS` (60).
- FILM node ids are `166` (`FrameInterpolationModelLoader`) and `167` (`FrameInterpolate`) in
  all three templates.
- Every phase ends green: `python -m pytest -q` for Python work, `npm test` +
  `npm run typecheck` for web work.

---

### Task 1: `interp` replaces `rife` in the domain

**Files:**
- Modify: `h3lab/domain/config.py`
- Modify: `h3lab/domain/arena.py:61-79`, `:222-226`
- Modify: `h3lab/domain/insights.py:58`
- Modify: `h3lab/storage/legacy.py:52-58`
- Test: `tests/test_domain_config.py`, `tests/test_domain_arena.py`

**Interfaces:**
- Produces: `Interp = Literal["off","film","rife"]`, `INTERP_MODES: tuple[Interp, ...]`,
  `INTERP_LABELS: dict[str, str]`, `GenerationConfig.interp`, `LEGACY_FIELD_ALIASES`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_legacy_rife_flag_is_read_as_an_interpolation_choice():
    assert GenerationConfig(first_frame="a.png", rife=True).interp == "rife"
    assert GenerationConfig(first_frame="a.png", rife=False).interp == "off"


def test_an_explicit_interpolation_choice_beats_the_legacy_flag():
    config = GenerationConfig(first_frame="a.png", rife=True, interp="film")
    assert config.interp == "film"


def test_interpolation_is_part_of_a_config_identity(base_config):
    assert config_hash(base_config.merged(interp="film")) != config_hash(base_config)
```

- [ ] **Step 2: Run to verify they fail**

`python -m pytest tests/test_domain_config.py -q -k interpolation` → FAIL,
`Extra inputs are not permitted [type=extra_forbidden]`.

- [ ] **Step 3: Implement**

```python
Interp = Literal["off", "film", "rife"]
INTERP_MODES: tuple[Interp, ...] = ("off", "film", "rife")
INTERP_LABELS: dict[str, str] = {"off": "Off", "film": "FILM Net", "rife": "RIFE"}
LEGACY_FIELD_ALIASES: frozenset[str] = frozenset({"rife"})
```

On `GenerationConfig`, replace `rife: bool = False` with `interp: Interp = "off"` and add:

```python
    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data: Any) -> Any:
        """`rife: bool` is what runs stored before interpolation had three answers."""
        if not isinstance(data, dict) or "rife" not in data:
            return data
        moved = dict(data)
        legacy = moved.pop("rife")
        if moved.get("interp") is None:
            moved["interp"] = "rife" if legacy else "off"
        return moved
```

Rename in `HASHED_FIELDS` and `FIELD_LABELS` (`"interp": "Interpolation"`), and in
`derive_label` use `if cfg.interp != "off": parts.append(cfg.interp)`. In `arena.py` swap
`"rife"` for `"interp"` in `HELD_FIELDS` and make `pool_label` read
`cfg.interp if cfg.interp != "off" else "no interp"`. In `insights.py` the axis becomes
`AxisDef(field="interp", label="Interpolation", kind="categorical")`. In `legacy.py` widen the
field filter to `key in GenerationConfig.model_fields or key in LEGACY_FIELD_ALIASES`.

- [ ] **Step 4: Run the domain suites**

`python -m pytest tests/test_domain_config.py tests/test_domain_arena.py tests/test_domain_insights.py -q`
→ PASS.

---

### Task 2: Migration v2 recomputes the hashes

**Files:**
- Modify: `h3lab/storage/migrations.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `Migration.fn: Callable[[sqlite3.Connection], None] | None`, migration version 2
  (`rename-rife-to-interp`), `LATEST_VERSION == 2`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_database_written_before_the_rename_opens_with_its_hashes_moved(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(migrations.MIGRATIONS[0].sql)
    legacy = {**LEGACY_CONFIG, "rife": True}
    conn.execute(
        "INSERT INTO runs (id, seq, label, status, mode, config_json, config_hash, "
        "recipe_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("r1", 1, "#1", "succeeded", "flf2v", json.dumps(legacy), "stale", "stale", "now"),
    )
    conn.commit()
    conn.close()

    store = open_store(path)
    run = RunRepository(store).require("r1")
    assert run.config.interp == "rife"
    assert run.config_hash == config_hash(run.config)
    assert run.recipe_hash == recipe_hash(run.config)
```

- [ ] **Step 2: Run to verify it fails**

`python -m pytest tests/test_storage.py -q -k rename` → FAIL, `assert 'stale' == '<digest>'`.

- [ ] **Step 3: Implement**

```python
@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    fn: Callable[[sqlite3.Connection], None] | None = None


def _rehash_configs(conn: sqlite3.Connection) -> None:
    """Renaming a hashed field moves every digest; stored ones have to move with it.

    A row whose config cannot be parsed is left exactly as it was. A benchmark result is
    worth more than a tidy schema.
    """
    from h3lab.domain.config import GenerationConfig, config_hash, recipe_hash

    for table, hashed in (("runs", True), ("presets", False)):
        rows = conn.execute(f"SELECT id, config_json FROM {table}").fetchall()
        for row in rows:
            try:
                config = GenerationConfig(**json.loads(row[1]))
            except Exception:
                continue
            payload = config.model_dump_json()
            if hashed:
                conn.execute(
                    f"UPDATE {table} SET config_json = ?, config_hash = ?, recipe_hash = ? "
                    "WHERE id = ?",
                    (payload, config_hash(config), recipe_hash(config), row[0]),
                )
            else:
                conn.execute(
                    f"UPDATE {table} SET config_json = ? WHERE id = ?", (payload, row[0])
                )
```

Append `Migration(version=2, name="rename-rife-to-interp", sql="", fn=_rehash_configs)` and
make `apply_migrations` skip an empty `sql` and call `fn` inside the version transaction.

- [ ] **Step 4: Run** `python -m pytest tests/test_storage.py -q` → PASS.

---

### Task 3: Three-way interpolation in the graph

**Files:**
- Modify: `h3lab/comfy/nodes.py`, `h3lab/comfy/graph.py:363-407`
- Test: `tests/test_comfy_graph.py`

**Interfaces:**
- Produces: `N.FILM_LOADER = 166`, `N.FILM_INTERP = 167`, `graph.FILM_MULTIPLIER = 2`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("mode", ["flf2v", "t2v", "r2v"])
def test_film_interpolation_is_wired_between_the_decode_and_the_combine(workflows, configs, mode):
    prompt = build(workflows[mode], configs[mode].merged(interp="film"))
    assert prompt[str(N.FILM_INTERP)]["inputs"]["images"] == [str(N.VAE_DECODE), 0]
    assert prompt[str(N.FILM_INTERP)]["inputs"]["interp_model"] == [str(N.FILM_LOADER), 0]
    assert prompt[str(N.VIDEO_COMBINE)]["inputs"]["images"] == [str(N.FILM_INTERP), 0]
    assert prompt[str(N.VIDEO_COMBINE)]["inputs"]["frame_rate"] == 48
    assert str(N.RIFE) not in prompt


def test_only_one_interpolator_survives(flf2v_workflow, base_config):
    rife = build(flf2v_workflow, base_config.merged(interp="rife"))
    assert str(N.FILM_INTERP) not in rife and str(N.FILM_LOADER) not in rife
    assert rife[str(N.VIDEO_COMBINE)]["inputs"]["frame_rate"] == 60
    off = build(flf2v_workflow, base_config)
    assert str(N.RIFE) not in off and str(N.FILM_INTERP) not in off
    assert off[str(N.VIDEO_COMBINE)]["inputs"]["frame_rate"] == 24
```

- [ ] **Step 2: Run to verify they fail**

`python -m pytest tests/test_comfy_graph.py -q -k interpolat` → FAIL, `KeyError: '167'`.

- [ ] **Step 3: Add the nodes to all three templates**

Write a one-off `scripts/_add_film_nodes.py`, run it against the three JSON files, verify, and
delete it. It must: append node 166 (`FrameInterpolationModelLoader`, `mode: 4`,
`widgets_values: ["film_net_fp16.safetensors"]`) and node 167 (`FrameInterpolate`, `mode: 4`,
`widgets_values: [2]`) positioned under the interpolation group; add links 166→167
(`interp_model`) and 125→167 (`images`), appending the new link ids to node 125's
`outputs[0].links`; rename the group title to `Frame Interpolation` and widen its bounding box
to contain the new nodes; bump `last_node_id` and `last_link_id`.

- [ ] **Step 4: Implement the wiring**

In `nodes.py` add the ids, `WIDGET_ORDER["FrameInterpolationModelLoader"] = ["model_name"]`
and `WIDGET_ORDER["FrameInterpolate"] = ["multiplier"]`. In `graph.py` replace the RIFE block
of `_wire_video_path`:

```python
    if config.interp == "rife" and has(prompt, N.RIFE) and images is not None:
        link(prompt, N.RIFE, "images", images, 0)
        images = N.RIFE
        drop(prompt, N.FILM_INTERP, N.FILM_LOADER)
    elif config.interp == "film" and has(prompt, N.FILM_INTERP) and images is not None:
        link(prompt, N.FILM_INTERP, "images", images, 0)
        widget(prompt, N.FILM_INTERP, "multiplier", FILM_MULTIPLIER)
        images = N.FILM_INTERP
        drop(prompt, N.RIFE)
    else:
        drop(prompt, N.RIFE, N.FILM_INTERP, N.FILM_LOADER)
        drop(prompt, N.INTERP_FPS)
```

and the frame rate:

```python
        if config.interp == "rife":
            fps = _primitive(prompt, N.INTERP_FPS, DEFAULT_INTERP_FPS)
        else:
            base = _primitive(prompt, N.BASE_FPS, DEFAULT_BASE_FPS)
            fps = base * FILM_MULTIPLIER if config.interp == "film" else base
```

- [ ] **Step 5: Run** `python -m pytest tests/test_comfy_graph.py -q` → PASS.

---

### Task 4: `h3lab/comfy/editor.py`

**Files:**
- Create: `h3lab/comfy/editor.py`
- Create: `tests/test_comfy_editor.py`

**Interfaces:**
- Produces: `to_editor_workflow(workflow, prompt, *, provenance=None) -> dict[str, Any]`.
- Consumes: `graph.to_api_prompt`, `graph.Prompt`, `nodes.WIDGET_ORDER`.

- [ ] **Step 1: Write the failing test — the round trip is the whole property**

```python
def test_the_exported_graph_reimports_as_the_prompt_it_came_from(flf2v_workflow, base_config):
    prompt = apply_config(flf2v_workflow, base_config.merged(interp="film"), output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    assert to_api_prompt(exported) == prompt


def test_the_exported_graph_is_the_editor_format_not_the_api_one(flf2v_workflow, base_config):
    exported = to_editor_workflow(
        flf2v_workflow, apply_config(flf2v_workflow, base_config, output_tag="r1")
    )
    assert {"nodes", "links", "groups", "extra"} <= set(exported)
    node = next(n for n in exported["nodes"] if n["id"] == N.VIDEO_COMBINE)
    assert node["widgets_values"]["filename_prefix"].endswith("r1")
    assert all(isinstance(link[0], int) and len(link) == 6 for link in exported["links"])
```

- [ ] **Step 2: Run to verify it fails**

`python -m pytest tests/test_comfy_editor.py -q` → FAIL,
`ModuleNotFoundError: No module named 'h3lab.comfy.editor'`.

- [ ] **Step 3: Implement**

Deep-copy the template. Index its nodes by id. For every prompt id build the node (template
node, or a synthesised `{"id", "type", "pos", "size", "flags", "order", "mode": 0, "inputs":
[], "outputs": [], "properties": {"Node name for S&R": class_type}, "widgets_values": []}`).
Reset each input slot's `link` to `None`, append slots for linked names the template lacks,
then walk the prompt's inputs: a `[source, slot]` pair mints a link
`[link_id, int(source), slot, int(node_id), input_index, type]`, appends `link_id` to the
source node's `outputs[slot]["links"]`, and sets the slot's `link`; any other value is written
into `widgets_values` by `WIDGET_ORDER` index (or by key when the template's
`widgets_values` is a dict). Keep `Note`/`MarkdownNote`, drop other UI-only types. Recompute
`last_node_id`/`last_link_id`, and merge `provenance` into `extra["h3lab"]`.

- [ ] **Step 4: Run** `python -m pytest tests/test_comfy_editor.py -q` → PASS, then extend
with the cases for dropped nodes, r2v references, and provenance, one at a time.

---

### Task 5: Submit the workflow with the prompt, and export it

**Files:**
- Modify: `h3lab/comfy/client.py:254-271`, `:302-340`
- Modify: `h3lab/engine/runner.py:265-284`
- Modify: `h3lab/engine/lab.py`
- Modify: `h3lab/api/routes/runs.py`
- Test: `tests/test_comfy_client.py`, `tests/test_engine.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `ComfyClient.queue(prompt, *, workflow=None)`,
  `ComfyClient.execute(prompt, *, workflow=None, ...)`, `Lab.workflow_for_run(run_id) -> dict`,
  `GET /api/runs/{run_id}/workflow`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_submitted_payload_carries_the_editor_workflow(fake_comfy):
    client.execute({"1": {"class_type": "X", "inputs": {}}}, track=False,
                   workflow={"nodes": [], "links": []})
    assert fake_comfy.last_payload["extra_data"]["extra_pnginfo"]["workflow"] == {
        "nodes": [], "links": []
    }
```

```python
async def test_a_run_can_be_downloaded_as_a_loadable_workflow(client, seeded_run):
    response = await client.get(f"/api/runs/{seeded_run}/workflow")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    assert body["nodes"] and body["links"] is not None
    assert body["extra"]["h3lab"]["run_id"] == seeded_run
```

- [ ] **Step 2: Run to verify they fail** → `KeyError: 'extra_data'` and `404`.

- [ ] **Step 3: Implement**

`queue` builds `payload = {"prompt": prompt, "client_id": self.client_id}` and adds
`payload["extra_data"] = {"extra_pnginfo": {"workflow": workflow}}` when `workflow` is not
`None`; `execute` forwards it. `Runner._execute` builds
`editor = to_editor_workflow(workflow, prompt, provenance={...})` and passes
`workflow=editor`. `Lab.workflow_for_run` loads the template for the run's mode, applies the
run's config with `output_tag=run.id`, and projects it. The route returns a `JSONResponse`
with the `Content-Disposition` header.

- [ ] **Step 4: Run** `python -m pytest tests/test_comfy_client.py tests/test_engine.py tests/test_api.py -q`
→ PASS.

---

### Task 6: The front end

**Files:**
- Modify: `h3lab/api/routes/lab.py` (Meta), then run `python scripts/gen_types.py`
- Modify: `web/src/api/routes.ts`, `web/src/pages/run.tsx`,
  `web/src/pages/lab/config-form.tsx:277-282`, `web/src/pages/lab/sweep-builder.tsx:33`,
  `web/src/test/harness.tsx:74`, `web/src/pages/arena/arena.test.tsx:17-18`
- Test: `web/src/pages/run.test.tsx`, `web/src/pages/lab/lab.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it("offers the three interpolation choices and queues the one picked", async () => {
  render(<Lab />)
  await user.click(await screen.findByRole("button", { name: "FILM Net" }))
  await user.click(screen.getByRole("button", { name: /queue/i }))
  expect(lastBody().config.interp).toBe("film")
})

it("offers the run's workflow as a download", async () => {
  render(<RunPage />)
  const link = await screen.findByRole("link", { name: /download workflow/i })
  expect(link).toHaveAttribute("href", "/api/runs/r1/workflow")
})
```

- [ ] **Step 2: Run to verify they fail** — `npm test -- run.test` → "Unable to find role".

- [ ] **Step 3: Implement** — `Meta` grows `interpolations: list[str]` and
`interpolation_labels: dict[str, str]`; the form swaps its `Toggle` for a labelled
`ToggleGroup` row with the hint "Off keeps 24 fps · FILM Net doubles to 48 · RIFE resamples to
60"; the sweep axis offers the three values; the Run page adds an anchor to
`routes.runWorkflow(id)` with `download`.

- [ ] **Step 4: Run** `npm test`, `npm run typecheck`, `npm run build`, and
`python -m pytest tests/test_contract.py -q` → all PASS.

---

### Task 7: Verify against the real thing, then document

- [ ] **Step 1: Three real generations.** With ComfyUI up, queue one tiny run per interpolation
  value through the running lab, wait for each, and `ffprobe` the produced file. Expect
  `avg_frame_rate` 24, 48 and 60.
- [ ] **Step 2: The PNG.** Locate the PNG VHS saved beside the last video in ComfyUI's output
  folder and assert its text chunks contain `workflow`, that the value parses, and that it has
  `nodes` and `links`. Run this **before** the client change to watch it go red.
- [ ] **Step 3: Suites.** `python -m pytest -q`, `npm test`, `npm run typecheck`,
  `npm run build`.
- [ ] **Step 4: Browser.** `python scripts/smoke.py`, or record the launcher error verbatim if
  Playwright cannot run here.
- [ ] **Step 5: Docs.** `CONTEXT.md` gains the frame-interpolation term and drops the
  RIFE-specific wording from the held-setting entries; `README.md` documents the export, the
  three-way setting, and that the export merges the run's config with the template as it is on
  disk now.
- [ ] **Step 6: Close the ledger** with the evidence, and fill the surface map's results table.

## Self-Review

- **Spec coverage:** export route → Task 5; editor projection → Task 4; PNG metadata →
  Task 5 + Task 7 step 2; three-way interpolation → Tasks 1 and 3; migration → Task 2; UI →
  Task 6; docs → Task 7.
- **Placeholders:** none; every step names its files, its code and its command.
- **Type consistency:** `to_editor_workflow`, `Lab.workflow_for_run`, `N.FILM_LOADER`,
  `N.FILM_INTERP`, `FILM_MULTIPLIER`, `Interp`, `INTERP_MODES`, `INTERP_LABELS` are spelled
  identically in every task that uses them.
