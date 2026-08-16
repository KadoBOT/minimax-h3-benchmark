from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from h3lab.domain.config import GenerationConfig
from h3lab.shared.contracts import JobSubmission, PublicJobProvenance
from h3lab.storage import LATEST_VERSION, RunRepository, open_store
from h3lab.storage.migrations import MIGRATIONS

REVISION = f"sha256:{'a' * 64}"
JOB_ID = "11111111-1111-4111-8111-111111111111"


def config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig(mode="t2v", prompt="A lighthouse", seed=seed)


def submission(seed: int = 42) -> JobSubmission:
    return JobSubmission(
        workflowRevision=REVISION,
        schemaRevision="h3-v1",
        input={"mode": "text_to_video", "prompt": "A lighthouse", "seed": seed},
    )


def provenance(seed: int = 42) -> PublicJobProvenance:
    return PublicJobProvenance(
        manifestDigest=f"sha256:{'b' * 64}",
        compiler={"id": "minimax-h3", "version": "1"},
        catalogRevision=f"sha256:{'c' * 64}",
        inputDigest=f"sha256:{'d' * 64}",
        resolvedSeed=seed,
    )


@pytest.mark.parametrize("old_version", [1, 2, 3, 4])
def test_every_existing_schema_version_gains_nullable_shared_columns(
    tmp_path: Path, old_version: int
):
    path = tmp_path / f"v{old_version}.db"
    conn = sqlite3.connect(path)
    conn.executescript(MIGRATIONS[0].sql)
    payload = config().model_dump_json()
    conn.execute(
        "INSERT INTO runs (id, seq, label, status, mode, config_json, config_hash, "
        "recipe_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "legacy",
            1,
            "#1 legacy",
            "succeeded",
            "t2v",
            payload,
            "old-cfg",
            "old-recipe",
            "x",
        ),
    )
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('schema_version', ?)",
        (str(old_version),),
    )
    conn.commit()
    conn.close()

    store = open_store(path)
    row = store().execute("SELECT * FROM runs WHERE id = 'legacy'").fetchone()
    assert row["shared_submission_json"] is None
    assert row["shared_job_id"] is None
    assert row["shared_provenance_json"] is None
    assert row["shared_event_cursor"] is None
    assert row["shared_failure_kind"] is None
    assert (
        int(
            store()
            .execute("SELECT value FROM app_state WHERE key = 'schema_version'")
            .fetchone()[0]
        )
        == LATEST_VERSION
    )


def test_shared_linkage_submission_provenance_and_cursor_round_trip(tmp_path: Path):
    runs = RunRepository(open_store(tmp_path / "shared.db"))
    made = runs.create(
        config(),
        run_id="local-run-1",
        shared_submission=submission(),
    )
    assert made.id == "local-run-1"
    assert made.shared_submission == submission()
    assert made.shared_job_id is None
    assert made.shared_event_cursor is None

    linked = runs.set_shared_job(made.id, JOB_ID, provenance())
    assert linked.shared_job_id == JOB_ID
    assert linked.shared_provenance == provenance()

    cursor = runs.set_shared_event_cursor(made.id, 9)
    assert cursor.shared_event_cursor == 9
    failed = runs.set_shared_failure(made.id, "collection_failed")
    assert failed.shared_failure_kind == "collection_failed"


def test_shared_rows_are_never_claimed_by_the_legacy_direct_runner(tmp_path: Path):
    runs = RunRepository(open_store(tmp_path / "claim.db"))
    shared = runs.create(config(), shared_submission=submission())
    legacy = runs.create(config(seed=43))
    claimed = runs.claim_next()
    assert claimed and claimed.id == legacy.id
    assert runs.require(shared.id).status == "queued"


def test_corrupt_shared_json_is_rejected_instead_of_silently_dropped(tmp_path: Path):
    store = open_store(tmp_path / "corrupt.db")
    runs = RunRepository(store)
    made = runs.create(config(), shared_submission=submission())
    conn = store()
    conn.execute(
        "UPDATE runs SET shared_submission_json = ? WHERE id = ?",
        (json.dumps({"schemaRevision": "missing-pinned-workflow"}), made.id),
    )
    conn.commit()
    with pytest.raises(ValidationError):
        runs.require(made.id)


def test_collection_failed_is_a_distinct_terminal_local_state(tmp_path: Path):
    runs = RunRepository(open_store(tmp_path / "collection.db"))
    made = runs.create(config(), shared_submission=submission())
    failed = runs.finish(made.id, "collection_failed", error="copy interrupted")
    assert failed.status == "collection_failed"
    assert failed.is_terminal
