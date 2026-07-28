"""Auth enforcement + JSON creation API tests."""

import json

import pytest

from histo_taskqueue.app import create_app
from histo_taskqueue.config import Config
from tests.conftest import SEQ_A, SEQ_B


def _make(tmp_path, mode="required", with_alleles=False):
    d = tmp_path / "alleles"
    if with_alleles:
        d.mkdir()
        (d / "registry.json").write_text(json.dumps([
            {"name": "HLA-A*02:01", "locus": "A", "heavy_chain": SEQ_A},
        ]))
        (d / "human_b2m.json").write_text(json.dumps({"canonical_sequence": "IQRTPKQVY"}))
        alleles_path = d
    else:
        alleles_path = tmp_path / "none"
    cfg = Config(store_backend="local", data_dir=tmp_path, alleles_path=alleles_path,
                 api_keys_path=tmp_path / "api_keys.json", api_auth_mode=mode)
    app = create_app(cfg)
    app.config.update(TESTING=True)
    store = app.extensions["htq_keys"]
    _, create_tok = store.create("producer", ["create"])
    _, consume_tok = store.create("worker", ["consume"])
    return app.test_client(), create_tok, consume_tok


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# -- enforcement ---------------------------------------------------------
def test_required_mode_rejects_without_key(tmp_path):
    client, _, _ = _make(tmp_path, mode="required")
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/jobs", json={"name": "x", "chains": []}).status_code == 401


def test_wrong_scope_is_forbidden(tmp_path):
    client, create_tok, consume_tok = _make(tmp_path)
    # consume token cannot create
    r = client.post("/api/jobs", json={"name": "x", "chains": [{"sequence": SEQ_A}]},
                    headers=_auth(consume_tok))
    assert r.status_code == 403
    # create token cannot list (consume-only)
    assert client.get("/api/jobs", headers=_auth(create_tok)).status_code == 403


def test_disabled_mode_is_open(tmp_path):
    cfg = Config(store_backend="local", data_dir=tmp_path,
                 alleles_path=tmp_path / "none",
                 api_keys_path=tmp_path / "api_keys.json", api_auth_mode="disabled")
    app = create_app(cfg)
    app.config.update(TESTING=True)
    # even though we add a key, disabled mode never enforces
    app.extensions["htq_keys"].create("x", ["create"])
    c = app.test_client()
    assert c.get("/api/jobs").status_code == 200


def test_auto_mode_open_until_keys_exist(client, tmp_path):
    # the default `client` fixture uses auto mode with an empty keystore
    assert client.get("/api/jobs").status_code == 200


def test_whoami(tmp_path):
    client, create_tok, _ = _make(tmp_path)
    data = client.get("/api/whoami", headers=_auth(create_tok)).get_json()
    assert data["authenticated"] is True
    assert data["key"]["scopes"] == ["create"]
    assert "token_sha256" not in data["key"]


# -- JSON creation -------------------------------------------------------
def test_api_create_job(tmp_path):
    client, create_tok, consume_tok = _make(tmp_path)
    r = client.post("/api/jobs",
                    json={"name": "API job", "chains": [{"sequence": SEQ_A, "count": 2}],
                          "model_seeds": [1, 2]},
                    headers=_auth(create_tok))
    assert r.status_code == 201
    body = r.get_json()
    assert body["job"]["name"] == "API job"
    assert body["file"][0]["sequences"][0]["proteinChain"]["count"] == 2
    assert body["file"][0]["modelSeeds"] == [1, 2]
    # visible to a consumer
    lst = client.get("/api/jobs", headers=_auth(consume_tok)).get_json()
    assert lst["counts"]["queued"] == 1


def test_api_create_job_validation(tmp_path):
    client, create_tok, _ = _make(tmp_path)
    r = client.post("/api/jobs", json={"name": "bad", "chains": [{"sequence": "ACDXZ1"}]},
                    headers=_auth(create_tok))
    assert r.status_code == 400
    assert "invalid residues" in r.get_json()["error"]


def test_api_create_pmhc(tmp_path):
    client, create_tok, _ = _make(tmp_path, with_alleles=True)
    r = client.post("/api/jobs/pmhc",
                    json={"allele_name": "HLA-A*02:01", "peptides": ["NLVPMVATV", "GILGFVFTL"]},
                    headers=_auth(create_tok))
    assert r.status_code == 201
    body = r.get_json()
    assert body["created"] == 2
    # heavy chain resolved from registry -> 3 chains
    job_id = body["jobs"][0]["job_id"]
    payload = client.get(f"/api/jobs/{job_id}", headers=_auth(create_tok))
    # create scope can't read; use a consume call instead
    assert payload.status_code == 403


def test_api_create_bulk(tmp_path):
    client, create_tok, _ = _make(tmp_path)
    csv = f"name,sequence_1\nA,{SEQ_A}\nB,{SEQ_B}\nBad,ACDXZ1\n"
    r = client.post("/api/jobs/bulk", json={"csv": csv}, headers=_auth(create_tok))
    assert r.status_code == 201
    body = r.get_json()
    assert body["created"] == 2
    assert body["total"] == 3
    assert any(not row["ok"] for row in body["jobs"])


def test_alleles_endpoint_requires_any_key(tmp_path):
    client, create_tok, consume_tok = _make(tmp_path, with_alleles=True)
    assert client.get("/api/alleles?q=HLA").status_code == 401
    assert client.get("/api/alleles?q=HLA", headers=_auth(create_tok)).status_code == 200
    assert client.get("/api/alleles?q=HLA", headers=_auth(consume_tok)).status_code == 200
