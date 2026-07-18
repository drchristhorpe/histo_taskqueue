"""The job queue — the seam between the object store and the DuckDB index.

A :class:`JobQueue` creates jobs (writing the AlphaFold file to the store and a
metadata row to the index), reads them back, advances their status through the
lifecycle, claims the next queued job FIFO, and deletes them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from . import alphafold
from .index import STATUSES, JobIndex, JobRecord
from .store import ObjectStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat(sep=" ")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class JobQueue:
    """Coordinates the object store and the index for the job lifecycle."""

    def __init__(self, store: ObjectStore, index: JobIndex):
        self.store = store
        self.index = index

    def create(
        self,
        name: str,
        chains: list[alphafold.ProteinChain],
        model_seeds: list[int] | None = None,
    ) -> JobRecord:
        """Validate + build a job, persist the JSON, and index it as ``queued``.

        Raises:
            alphafold.ValidationError: if the input is invalid.
        """
        job = alphafold.build_job(name, chains, model_seeds)
        job_id = _new_id()
        job_file = alphafold.build_job_file(job)

        self.store.put(job_id, job_file)
        now = _now_iso()
        record = JobRecord(
            id=job_id,
            name=job["name"],
            status="queued",
            num_chains=len(job["sequences"]),
            total_residues=alphafold.total_residues(job),
            chain_summary=alphafold.summarise_chains(job),
            model_seeds=", ".join(str(s) for s in job["modelSeeds"]),
            storage_key=job_id,
            location=self.store.location(job_id),
            created_at=now,
            updated_at=now,
        )
        self.index.upsert(record)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        return self.index.get(job_id)

    def get_job_file(self, job_id: str) -> Any:
        """Return the stored AlphaFold job file (the ``[ {...} ]`` array)."""
        return self.store.get(job_id)

    def list(self, status: str | None = None) -> list[JobRecord]:
        return self.index.list(status)

    def counts(self) -> dict[str, int]:
        return self.index.counts_by_status()

    def set_status(self, job_id: str, status: str) -> JobRecord | None:
        """Advance a job's status. Returns the updated record, or ``None``."""
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        if self.index.get(job_id) is None:
            return None
        self.index.set_status(job_id, status, _now_iso())
        return self.index.get(job_id)

    def claim_next(self) -> JobRecord | None:
        """Atomically-ish claim the oldest queued job, moving it to ``running``."""
        record = self.index.next_queued()
        if record is None:
            return None
        return self.set_status(record.id, "running")

    def delete(self, job_id: str) -> bool:
        """Delete a job from both the store and the index."""
        if self.index.get(job_id) is None:
            return False
        self.store.delete(job_id)
        self.index.delete(job_id)
        return True
