"""Token-based API keys with scopes for the JSON API.

Keys are random bearer tokens (``htq_<urlsafe>``). Only the SHA-256 hash of a
token is ever stored — the plaintext is shown once at creation and cannot be
recovered. Each key carries a set of scopes:

- ``create``  — create jobs (producers).
- ``consume`` — list jobs, claim the queue, set status (workers/consumers).
- ``admin``   — reserved for future privileged operations.

The store is a small JSON file (default ``data/api_keys.json``); manage it with
the ``histo-taskqueue-keys`` CLI.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCOPES = ("create", "consume", "admin")
TOKEN_PREFIX = "htq_"


class APIKeyError(ValueError):
    """Raised for invalid scope/token operations."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_token(token: str) -> str:
    """Return the hex SHA-256 of a token (what the store persists)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """Mint a new random bearer token, e.g. ``htq_x7Kd…``."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def validate_scopes(scopes: list[str]) -> list[str]:
    cleaned = []
    for s in scopes:
        s = s.strip().lower()
        if not s:
            continue
        if s not in SCOPES:
            raise APIKeyError(f"Unknown scope: {s!r}. Valid scopes: {', '.join(SCOPES)}.")
        if s not in cleaned:
            cleaned.append(s)
    if not cleaned:
        raise APIKeyError("At least one scope is required.")
    return cleaned


@dataclass
class APIKey:
    """A stored key record (never holds the plaintext token)."""

    id: str
    label: str
    scopes: list[str]
    token_sha256: str
    created_at: str
    revoked: bool = False

    def has_scope(self, scope: str) -> bool:
        return not self.revoked and ("admin" in self.scopes or scope in self.scopes)

    def public_dict(self) -> dict:
        d = asdict(self)
        d.pop("token_sha256", None)
        return d


class APIKeyStore:
    """A JSON-file-backed collection of API keys."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._keys: dict[str, APIKey] = {}          # id -> APIKey
        self._by_hash: dict[str, APIKey] = {}       # token_sha256 -> APIKey
        self.reload()

    # -- persistence -------------------------------------------------------
    def reload(self) -> None:
        self._keys = {}
        self._by_hash = {}
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        for item in data.get("keys", []):
            key = APIKey(
                id=item["id"],
                label=item.get("label", ""),
                scopes=list(item.get("scopes", [])),
                token_sha256=item["token_sha256"],
                created_at=item.get("created_at", ""),
                revoked=bool(item.get("revoked", False)),
            )
            self._keys[key.id] = key
            self._by_hash[key.token_sha256] = key

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"keys": [asdict(k) for k in self._keys.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- operations --------------------------------------------------------
    def create(self, label: str, scopes: list[str]) -> tuple[APIKey, str]:
        """Create a key. Returns (record, plaintext_token). Token shown once."""
        scopes = validate_scopes(scopes)
        token = generate_token()
        key = APIKey(
            id=uuid.uuid4().hex[:12],
            label=label.strip() or "unnamed",
            scopes=scopes,
            token_sha256=hash_token(token),
            created_at=_now_iso(),
            revoked=False,
        )
        self._keys[key.id] = key
        self._by_hash[key.token_sha256] = key
        self._save()
        return key, token

    def verify(self, token: str) -> APIKey | None:
        """Return the (non-revoked) key for a token, or None."""
        if not token:
            return None
        key = self._by_hash.get(hash_token(token))
        if key is None or key.revoked:
            return None
        return key

    def revoke(self, key_id: str) -> bool:
        key = self._keys.get(key_id)
        if key is None:
            return False
        key.revoked = True
        self._save()
        return True

    def list(self) -> list[APIKey]:
        return sorted(self._keys.values(), key=lambda k: k.created_at)

    def active_count(self) -> int:
        return sum(1 for k in self._keys.values() if not k.revoked)

    def __len__(self) -> int:
        return len(self._keys)
