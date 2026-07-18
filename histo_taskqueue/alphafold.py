"""Build and validate AlphaFold Server job files.

The AlphaFold Server ingests a JSON file that is an *array of jobs*. Each job has
a ``name``, ``modelSeeds`` (a list of integers, empty ⇒ server auto-assigns), a
list of ``sequences`` (entities), and the fixed keys ``dialect`` and ``version``.

This module models a single protein-chain job made of up to five chains and
serialises it to that exact format.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIALECT = "alphafoldserver"
VERSION = 1

#: The 20 standard amino acids accepted by the AlphaFold Server for protein chains.
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")

MAX_CHAINS = 5


class ValidationError(ValueError):
    """Raised when user input cannot be turned into a valid job."""


@dataclass
class ProteinChain:
    """A single protein chain entity.

    Attributes:
        sequence: One-letter amino-acid sequence (upper-case).
        count: Number of identical copies of this chain in the complex.
        glycans: Optional list of ``{"residues": str, "position": int}``.
        modifications: Optional list of ``{"ptmType": str, "ptmPosition": int}``.
    """

    sequence: str
    count: int = 1
    glycans: list[dict] = field(default_factory=list)
    modifications: list[dict] = field(default_factory=list)

    def to_entity(self) -> dict:
        chain: dict = {"sequence": self.sequence, "count": self.count}
        if self.glycans:
            chain["glycans"] = self.glycans
        if self.modifications:
            chain["modifications"] = self.modifications
        return {"proteinChain": chain}


def clean_sequence(raw: str) -> str:
    """Upper-case a sequence and strip all whitespace (incl. FASTA line breaks)."""
    return "".join(raw.split()).upper()


def validate_sequence(raw: str) -> str:
    """Clean and validate a protein sequence, returning the cleaned string.

    Raises:
        ValidationError: if the sequence is empty or contains non-standard letters.
    """
    seq = clean_sequence(raw)
    if not seq:
        raise ValidationError("Sequence is empty.")
    bad = sorted(set(seq) - AMINO_ACIDS)
    if bad:
        raise ValidationError(
            f"Sequence contains invalid residues: {', '.join(bad)}. "
            "Only the 20 standard amino acids are allowed."
        )
    return seq


def parse_model_seeds(raw: str | None) -> list[int]:
    """Parse a free-text seeds field (comma/space separated) into a list of ints."""
    if not raw or not raw.strip():
        return []
    tokens = raw.replace(",", " ").split()
    seeds: list[int] = []
    for tok in tokens:
        try:
            seeds.append(int(tok))
        except ValueError as exc:
            raise ValidationError(f"Model seed '{tok}' is not an integer.") from exc
    return seeds


def build_job(
    name: str,
    chains: list[ProteinChain],
    model_seeds: list[int] | None = None,
) -> dict:
    """Assemble a single job dict in AlphaFold Server format.

    Raises:
        ValidationError: on bad name, empty/too-many chains, or invalid residues.
    """
    name = (name or "").strip()
    if not name:
        raise ValidationError("Job name is required.")
    if not chains:
        raise ValidationError("At least one protein chain is required.")
    if len(chains) > MAX_CHAINS:
        raise ValidationError(f"A job may have at most {MAX_CHAINS} chains.")

    sequences = []
    for i, chain in enumerate(chains, start=1):
        seq = validate_sequence(chain.sequence)
        if chain.count < 1:
            raise ValidationError(f"Chain {i}: copy count must be at least 1.")
        sequences.append(
            ProteinChain(
                sequence=seq,
                count=chain.count,
                glycans=chain.glycans,
                modifications=chain.modifications,
            ).to_entity()
        )

    return {
        "name": name,
        "modelSeeds": list(model_seeds or []),
        "sequences": sequences,
        "dialect": DIALECT,
        "version": VERSION,
    }


def build_job_file(job: dict) -> list[dict]:
    """Wrap a single job in the array the AlphaFold Server expects."""
    return [job]


def summarise_chains(job: dict) -> str:
    """A short human summary of the chains, e.g. ``"128aa×1, 96aa×2"``."""
    parts = []
    for entity in job.get("sequences", []):
        chain = entity.get("proteinChain")
        if not chain:
            continue
        parts.append(f"{len(chain['sequence'])}aa×{chain.get('count', 1)}")
    return ", ".join(parts)


def total_residues(job: dict) -> int:
    """Total residues across all chains, accounting for copy count."""
    total = 0
    for entity in job.get("sequences", []):
        chain = entity.get("proteinChain")
        if chain:
            total += len(chain["sequence"]) * int(chain.get("count", 1))
    return total
