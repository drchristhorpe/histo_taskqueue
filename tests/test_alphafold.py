import pytest

from histo_taskqueue import alphafold as af


def test_build_job_basic():
    job = af.build_job("My job", [af.ProteinChain("mvls padk", 2)], [1, 2])
    assert job["name"] == "My job"
    assert job["dialect"] == "alphafoldserver"
    assert job["version"] == 1
    assert job["modelSeeds"] == [1, 2]
    assert job["sequences"] == [
        {"proteinChain": {"sequence": "MVLSPADK", "count": 2}}
    ]


def test_build_job_file_is_array():
    job = af.build_job("j", [af.ProteinChain("ACDEF")])
    assert af.build_job_file(job) == [job]


def test_clean_sequence_strips_and_uppercases():
    assert af.clean_sequence("mv ls\npa\tdk") == "MVLSPADK"


def test_validate_sequence_rejects_bad_residues():
    with pytest.raises(af.ValidationError):
        af.validate_sequence("ACDEFB123")  # B, digits are invalid


def test_validate_sequence_rejects_empty():
    with pytest.raises(af.ValidationError):
        af.validate_sequence("   ")


def test_empty_name_rejected():
    with pytest.raises(af.ValidationError):
        af.build_job("  ", [af.ProteinChain("ACDEF")])


def test_no_chains_rejected():
    with pytest.raises(af.ValidationError):
        af.build_job("j", [])


def test_too_many_chains_rejected():
    chains = [af.ProteinChain("ACDEF") for _ in range(af.MAX_CHAINS + 1)]
    with pytest.raises(af.ValidationError):
        af.build_job("j", chains)


def test_count_must_be_positive():
    with pytest.raises(af.ValidationError):
        af.build_job("j", [af.ProteinChain("ACDEF", 0)])


def test_parse_model_seeds():
    assert af.parse_model_seeds("1, 2 3,42") == [1, 2, 3, 42]
    assert af.parse_model_seeds("") == []
    assert af.parse_model_seeds(None) == []
    with pytest.raises(af.ValidationError):
        af.parse_model_seeds("1, x")


def test_summaries():
    job = af.build_job("j", [af.ProteinChain("ACDEF", 2), af.ProteinChain("ACD")])
    assert af.summarise_chains(job) == "5aa×2, 3aa×1"
    assert af.total_residues(job) == 5 * 2 + 3


def test_glycans_and_mods_included_when_present():
    chain = af.ProteinChain(
        "ACDEF",
        modifications=[{"ptmType": "CCD_HY3", "ptmPosition": 2}],
        glycans=[{"residues": "NAG", "position": 3}],
    )
    job = af.build_job("j", [chain])
    pc = job["sequences"][0]["proteinChain"]
    assert pc["modifications"] == [{"ptmType": "CCD_HY3", "ptmPosition": 2}]
    assert pc["glycans"] == [{"residues": "NAG", "position": 3}]
