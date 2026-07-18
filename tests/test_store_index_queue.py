import pytest

from histo_taskqueue import alphafold as af
from histo_taskqueue.store import LocalFileStore


# -- store ---------------------------------------------------------------
def test_local_store_roundtrip(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    store.put("abc", [{"hello": "world"}])
    assert store.exists("abc")
    assert store.get("abc") == [{"hello": "world"}]
    assert store.list_keys() == ["abc"]
    assert store.location("abc").endswith("abc.json")
    store.delete("abc")
    assert not store.exists("abc")
    assert store.list_keys() == []


def test_local_store_delete_missing_is_noop(tmp_path):
    store = LocalFileStore(tmp_path / "objects")
    store.delete("nope")  # must not raise


# -- queue lifecycle -----------------------------------------------------
def test_create_and_get(queue):
    rec = queue.create("Job 1", [af.ProteinChain("ACDEFGH", 2)])
    assert rec.status == "queued"
    assert rec.num_chains == 1
    assert rec.total_residues == 14
    fetched = queue.get(rec.id)
    assert fetched.name == "Job 1"
    job_file = queue.get_job_file(rec.id)
    assert isinstance(job_file, list)
    assert job_file[0]["dialect"] == "alphafoldserver"


def test_create_invalid_raises(queue):
    with pytest.raises(af.ValidationError):
        queue.create("bad", [af.ProteinChain("ACD123")])


def test_status_lifecycle(queue):
    rec = queue.create("Job", [af.ProteinChain("ACDEF")])
    updated = queue.set_status(rec.id, "running")
    assert updated.status == "running"
    assert queue.set_status("missing", "running") is None
    with pytest.raises(ValueError):
        queue.set_status(rec.id, "nonsense")


def test_claim_is_fifo(queue):
    a = queue.create("first", [af.ProteinChain("ACDEF")])
    b = queue.create("second", [af.ProteinChain("ACDEF")])
    claimed = queue.claim_next()
    assert claimed.id == a.id
    assert claimed.status == "running"
    # b is still queued and is next
    second = queue.claim_next()
    assert second.id == b.id
    assert queue.claim_next() is None  # nothing left queued


def test_counts_and_list_filter(queue):
    a = queue.create("a", [af.ProteinChain("ACDEF")])
    queue.create("b", [af.ProteinChain("ACDEF")])
    queue.set_status(a.id, "completed")
    counts = queue.counts()
    assert counts["queued"] == 1
    assert counts["completed"] == 1
    assert len(queue.list("completed")) == 1
    assert len(queue.list()) == 2


def test_delete(queue):
    rec = queue.create("a", [af.ProteinChain("ACDEF")])
    assert queue.delete(rec.id) is True
    assert queue.get(rec.id) is None
    assert queue.store.exists(rec.id) is False
    assert queue.delete("missing") is False
