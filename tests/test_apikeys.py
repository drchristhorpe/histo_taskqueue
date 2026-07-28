import pytest

from histo_taskqueue.apikeys import (
    APIKeyError,
    APIKeyStore,
    generate_token,
    hash_token,
    validate_scopes,
)


def test_generate_and_hash():
    t = generate_token()
    assert t.startswith("htq_")
    assert hash_token(t) == hash_token(t)          # deterministic
    assert hash_token(t) != hash_token(generate_token())


def test_validate_scopes():
    assert validate_scopes(["create", "consume", "create"]) == ["create", "consume"]
    with pytest.raises(APIKeyError):
        validate_scopes(["nonsense"])
    with pytest.raises(APIKeyError):
        validate_scopes([])


def test_store_create_verify_revoke(tmp_path):
    store = APIKeyStore(tmp_path / "keys.json")
    key, token = store.create("worker", ["consume"])
    assert token.startswith("htq_")
    assert store.active_count() == 1

    verified = store.verify(token)
    assert verified is not None
    assert verified.id == key.id
    assert verified.has_scope("consume")
    assert not verified.has_scope("create")
    assert store.verify("htq_wrong") is None

    # persistence: a fresh store over the same file sees the key
    reloaded = APIKeyStore(tmp_path / "keys.json")
    assert reloaded.verify(token) is not None

    assert store.revoke(key.id) is True
    assert store.verify(token) is None
    assert store.active_count() == 0
    assert store.revoke("missing") is False


def test_admin_scope_grants_all(tmp_path):
    store = APIKeyStore(tmp_path / "keys.json")
    _, token = store.create("admin", ["admin"])
    key = store.verify(token)
    assert key.has_scope("create")
    assert key.has_scope("consume")


def test_public_dict_hides_hash(tmp_path):
    store = APIKeyStore(tmp_path / "keys.json")
    key, _ = store.create("x", ["create"])
    assert "token_sha256" not in key.public_dict()
