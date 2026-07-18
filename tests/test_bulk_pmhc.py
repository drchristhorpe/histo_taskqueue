import json

import pytest

from histo_taskqueue import alphafold as af
from histo_taskqueue import bulk, pmhc
from histo_taskqueue.alleles import AlleleRegistry


# -- bulk CSV ------------------------------------------------------------
def test_parse_jobs_csv_basic():
    text = (
        "name,sequence_1,count_1,sequence_2,count_2,model_seeds\n"
        "Homodimer,MVLSPADK,2,,,\n"
        "Hetero,MVLSPADK,1,ACDEFGH,1,\"1, 2\"\n"
    )
    results = bulk.parse_jobs_csv(text)
    assert len(results) == 2
    assert all(r.ok for r in results)
    homodimer = results[0].spec
    assert homodimer.name == "Homodimer"
    assert len(homodimer.chains) == 1
    assert homodimer.chains[0].count == 2
    hetero = results[1].spec
    assert len(hetero.chains) == 2
    assert hetero.model_seeds == [1, 2]


def test_parse_jobs_csv_reports_row_errors():
    text = "name,sequence_1\nGood,ACDEF\nBadResidue,ACDXZ1\n,ACDEF\n"
    results = bulk.parse_jobs_csv(text)
    assert results[0].ok
    assert not results[1].ok and "invalid residues" in results[1].error
    assert not results[2].ok  # empty name


def test_parse_jobs_csv_bad_count():
    text = "name,sequence_1,count_1\nJ,ACDEF,two\n"
    results = bulk.parse_jobs_csv(text)
    assert not results[0].ok and "whole number" in results[0].error


def test_parse_jobs_csv_missing_name_column():
    with pytest.raises(af.ValidationError):
        bulk.parse_jobs_csv("foo,sequence_1\nx,ACDEF\n")


def test_sample_csv_is_parseable():
    results = bulk.parse_jobs_csv(bulk.SAMPLE_CSV)
    assert results and all(r.ok for r in results)


# -- pMHC ----------------------------------------------------------------
def test_parse_peptides_dedupes_and_cleans():
    assert pmhc.parse_peptides("nlv pmvatv\nGILGFVFTL, NLVPMVATV\n\n") == [
        "NLVPMVATV",
        "GILGFVFTL",
    ]


def test_build_pmhc_specs_three_chains_with_default_b2m():
    specs = pmhc.build_pmhc_specs("HLA-A*02:01", "ACDEFGHIK", ["NLVPMVATV", "GILGFVFTL"])
    assert len(specs) == 2
    first = specs[0]
    assert first.name == "HLA-A*02:01 + NLVPMVATV"
    assert len(first.chains) == 3
    assert first.chains[0].sequence == "ACDEFGHIK"
    assert first.chains[1].sequence == pmhc.DEFAULT_B2M
    assert first.chains[2].sequence == "NLVPMVATV"


def test_build_pmhc_specs_without_b2m():
    specs = pmhc.build_pmhc_specs("A2", "ACDEFGHIK", ["NLVPMVATV"], include_b2m=False)
    assert len(specs[0].chains) == 2


def test_build_pmhc_specs_validation():
    with pytest.raises(af.ValidationError):
        pmhc.build_pmhc_specs("", "ACDEF", ["NLVPMVATV"])
    with pytest.raises(af.ValidationError):
        pmhc.build_pmhc_specs("A2", "", ["NLVPMVATV"])
    with pytest.raises(af.ValidationError):
        pmhc.build_pmhc_specs("A2", "ACDEF", [])


# -- allele registry -----------------------------------------------------
def test_allele_registry_loads(tmp_path):
    path = tmp_path / "alleles.json"
    path.write_text(json.dumps([
        {"name": "HLA-A*02:01", "heavy_chain": "ACDEFGHIK", "b2m": "IQRTPK"},
        {"name": "bad", "heavy_chain": ""},  # skipped
    ]))
    reg = AlleleRegistry(path)
    assert len(reg) == 1
    a = reg.get("HLA-A*02:01")
    assert a.heavy_chain == "ACDEFGHIK"
    assert reg.get("nope") is None


def test_allele_registry_missing_file(tmp_path):
    reg = AlleleRegistry(tmp_path / "does_not_exist.json")
    assert len(reg) == 0
    assert reg.list() == []
