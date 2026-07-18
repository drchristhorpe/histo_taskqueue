"""DuckDB-backed index over queued jobs.

The object store is the source of truth (it holds the full AlphaFold job files);
this index holds queryable *metadata* so the queue can be listed, filtered by
status and summarised quickly. It can be rebuilt from the store at any time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

STATUSES = ("queued", "running", "completed", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           VARCHAR PRIMARY KEY,
    name         VARCHAR NOT NULL,
    status       VARCHAR NOT NULL DEFAULT 'queued',
    num_chains   INTEGER NOT NULL DEFAULT 0,
    total_residues INTEGER NOT NULL DEFAULT 0,
    chain_summary  VARCHAR,
    model_seeds  VARCHAR,
    storage_key  VARCHAR,
    location     VARCHAR,
    created_at   TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP NOT NULL
);
"""


@dataclass
class JobRecord:
    """One row of the index."""

    id: str
    name: str
    status: str
    num_chains: int
    total_residues: int
    chain_summary: str
    model_seeds: str
    storage_key: str
    location: str
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_COLUMNS = [
    "id",
    "name",
    "status",
    "num_chains",
    "total_residues",
    "chain_summary",
    "model_seeds",
    "storage_key",
    "location",
    "created_at",
    "updated_at",
]


class JobIndex:
    """Thin wrapper over a DuckDB connection holding the ``jobs`` table."""

    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._con = duckdb.connect(self.path)
        self._con.execute(_SCHEMA)

    def close(self) -> None:
        self._con.close()

    # -- writes ------------------------------------------------------------
    def upsert(self, record: JobRecord) -> None:
        """Insert or replace a job row."""
        values = [getattr(record, col) for col in _COLUMNS]
        placeholders = ", ".join("?" for _ in _COLUMNS)
        self._con.execute(
            f"INSERT OR REPLACE INTO jobs ({', '.join(_COLUMNS)}) "
            f"VALUES ({placeholders})",
            values,
        )

    def set_status(self, job_id: str, status: str, updated_at: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        self._con.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            [status, updated_at, job_id],
        )

    def delete(self, job_id: str) -> None:
        self._con.execute("DELETE FROM jobs WHERE id = ?", [job_id])

    # -- reads -------------------------------------------------------------
    def _row_to_record(self, row: tuple) -> JobRecord:
        data = dict(zip(_COLUMNS, row))
        data["created_at"] = str(data["created_at"])
        data["updated_at"] = str(data["updated_at"])
        return JobRecord(**data)

    def get(self, job_id: str) -> JobRecord | None:
        row = self._con.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM jobs WHERE id = ?", [job_id]
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list(self, status: str | None = None) -> list[JobRecord]:
        """List jobs, optionally filtered by status, newest first."""
        sql = f"SELECT {', '.join(_COLUMNS)} FROM jobs"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        rows = self._con.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def next_queued(self) -> JobRecord | None:
        """The oldest job with status ``queued`` (FIFO), or ``None``."""
        row = self._con.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM jobs "
            "WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return self._row_to_record(row) if row else None

    def counts_by_status(self) -> dict[str, int]:
        """A status→count map covering every known status (zero-filled)."""
        rows = self._con.execute(
            "SELECT status, COUNT(*) FROM jobs GROUP BY status"
        ).fetchall()
        counts = {s: 0 for s in STATUSES}
        for status, n in rows:
            counts[status] = n
        return counts
