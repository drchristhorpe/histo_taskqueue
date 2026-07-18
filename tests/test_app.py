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
