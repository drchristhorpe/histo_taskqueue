"""Build pMHC class I jobs — one MHC allele against many peptides.

A peptide-MHC class I complex is modelled as up to three protein chains:

1. the MHC heavy chain (the HLA allele),
2. β2-microglobulin (optional; defaults to the human sequence below), and
3. the peptide.

Given one allele and a list of peptides, :func:`build_pmhc_specs` produces one
:class:`~histo_taskqueue.alphafold.JobSpec` per peptide, so a whole panel can be
queued in a single submission.
"""

from __future__ import annotations

from . import alphafold

#: Mature human β2-microglobulin (used when an allele defines no β2m of its own).
DEFAULT_B2M = (
    "IQRTPKIQVYSRHPAENGKSNFLNCYVSGFHPSDIEVDLLKNGERIEKVEHSDLSFSKDW"
    "SFYLLYYTEFTPTEKDEYACRVNHVTLSQPKIVKWDRDM"
)


def parse_peptides(text: str) -> list[str]:
    """Split a free-text block (newlines and/or commas) into peptide strings.

    Sequences are upper-cased and de-whitespaced; blank lines are dropped;
    order is preserved and duplicates are removed.
    """
    tokens: list[str] = []
    for line in (text or "").replace(",", "\n").splitlines():
        pep = alphafold.clean_sequence(line)
        if pep:
            tokens.append(pep)
    seen: set[str] = set()
    unique: list[str] = []
    for pep in tokens:
        if pep not in seen:
            seen.add(pep)
            unique.append(pep)
    return unique


def build_pmhc_specs(
    allele_name: str,
    heavy_chain: str,
    peptides: list[str],
    b2m: str | None = None,
    include_b2m: bool = True,
    heavy_count: int = 1,
    b2m_count: int = 1,
) -> list[alphafold.JobSpec]:
    """One job spec per peptide: ``[heavy, (β2m), peptide]``.

    Raises:
        alphafold.ValidationError: for a missing allele name/heavy chain or no
            peptides. Per-peptide residue validation happens when each spec is
            built into a job.
    """
    allele_name = (allele_name or "").strip()
    if not allele_name:
        raise alphafold.ValidationError("An allele name is required.")
    heavy_chain = alphafold.clean_sequence(heavy_chain)
    if not heavy_chain:
        raise alphafold.ValidationError("The MHC heavy-chain sequence is required.")
    if not peptides:
        raise alphafold.ValidationError("Provide at least one peptide sequence.")

    b2m_seq = alphafold.clean_sequence(b2m) if b2m else DEFAULT_B2M

    specs: list[alphafold.JobSpec] = []
    for pep in peptides:
        chains = [alphafold.ProteinChain(sequence=heavy_chain, count=heavy_count)]
        if include_b2m:
            chains.append(alphafold.ProteinChain(sequence=b2m_seq, count=b2m_count))
        chains.append(alphafold.ProteinChain(sequence=pep, count=1))
        specs.append(
            alphafold.JobSpec(name=f"{allele_name} + {pep}", chains=chains)
        )
    return specs
