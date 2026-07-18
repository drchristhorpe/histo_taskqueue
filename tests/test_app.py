import io
import json

from tests.conftest import SEQ_A, SEQ_B


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_empty_queue_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"No jobs" in resp.data


def test_new_job_form_renders(client):
    resp = client.get("/jobs/new")
    assert resp.status_code == 200
    assert b"Compose a job" in resp.data
    # 5 chain slots
    assert resp.data.count(b"chain-card") == 5


def test_create_job_flow(client):
    resp = client.post(
        "/jobs",
        data={
            "name": "Complex A",
            "model_seeds": "1, 2",
            "sequence_1": SEQ_A,
            "count_1": "1",
            "sequence_2": SEQ_B,
            "count_2": "2",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Complex A" in resp.data
    assert b"queued" in resp.data
    # appears on the queue listing too
    listing = client.get("/").data
    assert b"Complex A" in listing


def test_create_job_validation_error(client):
    resp = client.post(
        "/jobs",
        data={"name": "Bad", "sequence_1": "ACD123"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"invalid residues" in resp.data


def test_create_job_requires_a_chain(client):
    resp = client.post("/jobs", data={"name": "NoChains"}, follow_redirects=True)
    assert b"At least one protein chain" in resp.data


def test_download_job_file(client):
    client.post("/jobs", data={"name": "DL", "sequence_1": SEQ_A}, follow_redirects=True)
    job_id = client.get("/api/jobs").get_json()["jobs"][0]["id"]
    resp = client.get(f"/jobs/{job_id}/download")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]
    payload = json.loads(resp.data)
    assert isinstance(payload, list)
    assert payload[0]["dialect"] == "alphafoldserver"
    assert payload[0]["sequences"][0]["proteinChain"]["sequence"] == SEQ_A


def test_status_update_and_delete(client):
    client.post("/jobs", data={"name": "S", "sequence_1": SEQ_A}, follow_redirects=True)
    job_id = client.get("/api/jobs").get_json()["jobs"][0]["id"]

    resp = client.post(f"/jobs/{job_id}/status", data={"status": "completed"}, follow_redirects=True)
    assert b"completed" in resp.data

    resp = client.post(f"/jobs/{job_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_api_claim(client):
    client.post("/jobs", data={"name": "C1", "sequence_1": SEQ_A}, follow_redirects=True)
    resp = client.post("/api/jobs/claim")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["job"]["status"] == "running"
    assert data["file"][0]["dialect"] == "alphafoldserver"
    # nothing left to claim
    assert client.post("/api/jobs/claim").status_code == 204


def test_api_set_status(client):
    client.post("/jobs", data={"name": "AS", "sequence_1": SEQ_A}, follow_redirects=True)
    job_id = client.get("/api/jobs").get_json()["jobs"][0]["id"]
    resp = client.post(f"/api/jobs/{job_id}/status", json={"status": "completed"})
    assert resp.status_code == 200
    assert resp.get_json()["job"]["status"] == "completed"
    bad = client.post(f"/api/jobs/{job_id}/status", json={"status": "nope"})
    assert bad.status_code == 400
    assert client.post("/api/jobs/missing/status", json={"status": "queued"}).status_code == 404


def test_404_for_missing_job(client):
    assert client.get("/jobs/deadbeef").status_code == 404


# -- bulk CSV upload -----------------------------------------------------
def test_upload_page_and_sample(client):
    assert b"Bulk upload" in client.get("/jobs/upload").data
    sample = client.get("/jobs/upload/sample.csv")
    assert sample.status_code == 200
    assert sample.mimetype == "text/csv"
    assert b"name,sequence_1" in sample.data


def test_upload_csv_text_creates_jobs(client):
    csv_text = (
        "name,sequence_1,count_1,sequence_2,count_2\n"
        f"Row A,{SEQ_A},1,,\n"
        f"Row B,{SEQ_A},1,{SEQ_B},2\n"
        "Row Bad,ACDXZ1,1,,\n"
    )
    resp = client.post("/jobs/upload", data={"csv_text": csv_text}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"created <strong>2</strong> of 3" in resp.data
    # two good jobs are now queued
    assert client.get("/api/jobs").get_json()["counts"]["queued"] == 2


def test_upload_file_creates_jobs(client):
    csv_bytes = f"name,sequence_1\nFromFile,{SEQ_A}\n".encode()
    data = {"file": (io.BytesIO(csv_bytes), "jobs.csv")}
    resp = client.post("/jobs/upload", data=data, content_type="multipart/form-data",
                       follow_redirects=True)
    assert b"FromFile" in resp.data
    assert client.get("/api/jobs").get_json()["counts"]["queued"] == 1


def test_upload_missing_name_column_flashes(client):
    resp = client.post("/jobs/upload", data={"csv_text": "foo\nbar\n"}, follow_redirects=True)
    assert b"must have a &#39;name&#39; column" in resp.data or b"name" in resp.data


# -- pMHC panel ----------------------------------------------------------
def test_pmhc_page(client):
    resp = client.get("/jobs/pmhc")
    assert resp.status_code == 200
    assert b"pMHC class I panel" in resp.data


def test_pmhc_submit_creates_one_job_per_peptide(client):
    resp = client.post(
        "/jobs/pmhc",
        data={
            "allele_name": "HLA-A*02:01",
            "heavy_chain": SEQ_A,
            "include_b2m": "on",
            "peptides": "NLVPMVATV\nGILGFVFTL, NLVPMVATV",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # two unique peptides -> two jobs
    assert b"created <strong>2</strong> of 2" in resp.data
    jobs = client.get("/api/jobs").get_json()["jobs"]
    assert len(jobs) == 2
    # each job has 3 chains (heavy + b2m + peptide)
    assert all(j["num_chains"] == 3 for j in jobs)
    names = {j["name"] for j in jobs}
    assert "HLA-A*02:01 + NLVPMVATV" in names


def test_pmhc_submit_without_b2m(client):
    resp = client.post(
        "/jobs/pmhc",
        data={"allele_name": "A2", "heavy_chain": SEQ_A, "peptides": "NLVPMVATV"},
        follow_redirects=True,
    )
    assert b"created <strong>1</strong> of 1" in resp.data
    assert client.get("/api/jobs").get_json()["jobs"][0]["num_chains"] == 2


def test_pmhc_submit_validation_error(client):
    resp = client.post("/jobs/pmhc", data={"allele_name": "", "heavy_chain": SEQ_A,
                                           "peptides": "NLVPMVATV"}, follow_redirects=True)
    assert b"allele name is required" in resp.data
