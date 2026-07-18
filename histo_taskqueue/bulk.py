"""Bulk job creation from CSV.

Users can submit many jobs at once with a wide-format CSV — one job per row.

Recognised columns (header row required, case-insensitive; surrounding
whitespace ignored):

- ``name``                     — required, the job name.
- ``sequence_1`` … ``sequence_5`` — protein-chain sequences; ``sequence_1`` is
  required, the rest optional. Blank cells are skipped.
- ``count_1`` … ``count_5``    — optional copy counts per chain (default 1).
- ``model_seeds``              — optional, comma/space separated integers.

Parsing is intentionally lenient about the *structure* (missing optional
columns are fine) but strict about *content* — amino-acid validation happens when
each row is turned into a :class:`~histo_taskqueue.alphafold.JobSpec`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from . import alphafold

MAX_CHAINS = alphafold.MAX_CHAINS

SAMPLE_CSV = (
    "name,sequence_1,count_1,sequence_2,count_2,model_seeds\n"
    "Homodimer example,MVLSPADKTNVKAAWGKVGAHAGEY,2,,,\n"
    "Heterodimer example,MVLSPADKTNVKAAWGKVGAHAGEY,1,MVHLTPEEKSAVTALWGKVNVDEV,1,\"1, 2\"\n"
    "Single chain + seeds,SLLMWITQV,1,,,42\n"
)


@dataclass
class RowResult:
    """The outcome of parsing (and later, creating) one CSV row."""

    row_num: int
    name: str
    spec: alphafold.JobSpec | None = None
    error: str | None = None
    job_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _norm_header(name: str) -> str:
    return (name or "").strip().lower()


def parse_jobs_csv(text: str) -> list[RowResult]:
    """Parse CSV text into one :class:`RowResult` per data row.

    Each result carries either a validated ``spec`` or an ``error`` string. The
    caller is responsible for turning specs into queued jobs.
    """
    text = text.lstrip("﻿")  # strip a UTF-8 BOM if present
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []

    fields = {_norm_header(f): f for f in reader.fieldnames}
    if "name" not in fields:
        raise alphafold.ValidationError(
            "CSV must have a 'name' column. See the sample CSV for the format."
        )
    if not any(f.startswith("sequence_") for f in fields):
        raise alphafold.ValidationError(
            "CSV must have at least a 'sequence_1' column."
        )

    results: list[RowResult] = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        norm = { _norm_header(k): (v or "") for k, v in row.items() }
        name = norm.get("name", "").strip()
        try:
            chains = _row_chains(norm)
            seeds = alphafold.parse_model_seeds(norm.get("model_seeds", ""))
            spec = alphafold.JobSpec(name=name, chains=chains, model_seeds=seeds)
            # Validate now so parse errors surface before we touch the queue.
            spec.to_job()
            results.append(RowResult(row_num=i, name=name, spec=spec))
        except alphafold.ValidationError as exc:
            results.append(RowResult(row_num=i, name=name, error=str(exc)))
    return results


def _row_chains(norm: dict[str, str]) -> list[alphafold.ProteinChain]:
    chains: list[alphafold.ProteinChain] = []
    for n in range(1, MAX_CHAINS + 1):
        seq = norm.get(f"sequence_{n}", "").strip()
        if not seq:
            continue
        count_raw = norm.get(f"count_{n}", "").strip() or "1"
        try:
            count = int(count_raw)
        except ValueError as exc:
            raise alphafold.ValidationError(
                f"Chain {n}: copies '{count_raw}' is not a whole number."
            ) from exc
        chains.append(alphafold.ProteinChain(sequence=seq, count=count))
    return chains
