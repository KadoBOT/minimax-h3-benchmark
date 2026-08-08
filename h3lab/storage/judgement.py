"""Rating and vote persistence."""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from h3lab.domain.ids import new_id
from h3lab.domain.rating import EloEntry, Rating, Vote, replay_elo
from h3lab.storage.db import ConnectionFactory, scalar, session, transaction
from h3lab.storage.runs import RunNotFound, utc_now


class RatingRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def put(self, run_id: str, stars: int, criteria: dict[str, int] | None = None) -> Rating:
        rating = Rating(run_id=run_id, stars=stars, criteria=criteria or {}, updated_at=utc_now())
        with session(self._connect) as conn, transaction(conn):
            if scalar(conn, "SELECT 1 FROM runs WHERE id = ?", (run_id,)) is None:
                raise RunNotFound(run_id)
            conn.execute(
                """
                INSERT INTO ratings (run_id, stars, criteria_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    stars = excluded.stars,
                    criteria_json = excluded.criteria_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    rating.stars,
                    json.dumps(rating.criteria),
                    rating.updated_at,
                ),
            )
        return rating

    def get(self, run_id: str) -> Rating | None:
        with session(self._connect) as conn:
            row = conn.execute("SELECT * FROM ratings WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Rating(
            run_id=row["run_id"],
            stars=int(row["stars"]),
            criteria=json.loads(row["criteria_json"] or "{}"),
            updated_at=row["updated_at"],
        )

    def delete(self, run_id: str) -> bool:
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute("DELETE FROM ratings WHERE run_id = ?", (run_id,))
            return cursor.rowcount > 0

    def all_map(self) -> dict[str, Rating]:
        with session(self._connect) as conn:
            rows = conn.execute("SELECT * FROM ratings").fetchall()
        return {
            row["run_id"]: Rating(
                run_id=row["run_id"],
                stars=int(row["stars"]),
                criteria=json.loads(row["criteria_json"] or "{}"),
                updated_at=row["updated_at"],
            )
            for row in rows
        }

    def stars_map(self) -> dict[str, int]:
        with session(self._connect) as conn:
            rows = conn.execute("SELECT run_id, stars FROM ratings").fetchall()
        return {row["run_id"]: int(row["stars"]) for row in rows}


class VoteRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def add(
        self,
        run_a: str,
        run_b: str,
        winner: str | None,
        *,
        axis: str | None = None,
    ) -> Vote:
        if run_a == run_b:
            raise ValueError("a run cannot be compared with itself")
        if winner is not None and winner not in (run_a, run_b):
            raise ValueError("winner must be one of the two runs, or null for a tie")
        vote = Vote(
            id=new_id(),
            run_a=run_a,
            run_b=run_b,
            winner=winner,
            axis=axis,
            created_at=utc_now(),
        )
        with session(self._connect) as conn, transaction(conn):
            for run_id in (run_a, run_b):
                if scalar(conn, "SELECT 1 FROM runs WHERE id = ?", (run_id,)) is None:
                    raise RunNotFound(run_id)
            conn.execute(
                "INSERT INTO votes (id, run_a, run_b, winner, axis, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vote.id, vote.run_a, vote.run_b, vote.winner, vote.axis, vote.created_at),
            )
        return vote

    def list(self, *, limit: int = 1000) -> list[Vote]:
        with session(self._connect) as conn:
            rows = conn.execute(
                "SELECT * FROM votes ORDER BY created_at ASC, id ASC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Vote(
                id=row["id"],
                run_a=row["run_a"],
                run_b=row["run_b"],
                winner=row["winner"],
                axis=row["axis"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def for_run(self, run_id: str) -> list[Vote]:
        return [vote for vote in self.list() if run_id in (vote.run_a, vote.run_b)]

    def count(self) -> int:
        with session(self._connect) as conn:
            return int(scalar(conn, "SELECT COUNT(*) FROM votes") or 0)

    def delete(self, vote_id: str) -> bool:
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute("DELETE FROM votes WHERE id = ?", (vote_id,))
            return cursor.rowcount > 0

    def elo(self) -> dict[str, EloEntry]:
        """Replayed from the whole log, so the numbers are always reproducible."""
        return replay_elo(self.list(limit=1_000_000))

    def elo_ratings(self) -> dict[str, float]:
        return {run_id: entry.rating for run_id, entry in self.elo().items()}


def elo_for(votes: Iterable[Vote] | Sequence[Vote]) -> dict[str, EloEntry]:
    return replay_elo(votes)
