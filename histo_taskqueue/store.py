"""Pluggable JSON object store.

The store holds the *source of truth*: the AlphaFold Server job file for each
job, keyed by job id. Two backends are provided:

- :class:`LocalFileStore` — writes ``<objects_dir>/<key>.json`` (default).
- :class:`S3Store` — writes ``s3://<bucket>/<prefix>/<key>.json`` (needs boto3).

Both implement the :class:`ObjectStore` interface so the rest of the app is
storage-agnostic.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .config import Config


class ObjectStore(ABC):
    """Interface for a keyed JSON object store."""

    @abstractmethod
    def put(self, key: str, obj: Any) -> None:
        """Serialise ``obj`` to JSON and store it under ``key``."""

    @abstractmethod
    def get(self, key: str) -> Any:
        """Load and deserialise the JSON stored under ``key``."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object under ``key`` (no error if it is absent)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an object exists under ``key``."""

    @abstractmethod
    def list_keys(self) -> list[str]:
        """Return all keys currently in the store."""

    @abstractmethod
    def location(self, key: str) -> str:
        """A human-readable location string for ``key`` (path or s3 URI)."""


class LocalFileStore(ObjectStore):
    """Store JSON objects as pretty-printed files on the local filesystem."""

    def __init__(self, objects_dir: Path):
        self.objects_dir = Path(objects_dir)
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.objects_dir / f"{key}.json"

    def put(self, key: str, obj: Any) -> None:
        path = self._path(key)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic on POSIX

    def get(self, key: str) -> Any:
        return json.loads(self._path(key).read_text(encoding="utf-8"))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self) -> list[str]:
        return sorted(p.stem for p in self.objects_dir.glob("*.json"))

    def location(self, key: str) -> str:
        return str(self._path(key))


class S3Store(ObjectStore):
    """Store JSON objects in an S3 bucket under a key prefix."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "jobs",
        endpoint_url: str | None = None,
    ):
        try:
            import boto3  # imported lazily so boto3 is only needed for S3
        except ImportError as exc:  # pragma: no cover - exercised only without boto3
            raise RuntimeError(
                "The S3 backend requires boto3. Install with: uv sync --extra s3"
            ) from exc
        if not bucket:
            raise ValueError("HTQ_S3_BUCKET must be set for the s3 backend.")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._s3 = boto3.client("s3", endpoint_url=endpoint_url)

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}.json" if self.prefix else f"{key}.json"

    def put(self, key: str, obj: Any) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=json.dumps(obj, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

    def get(self, key: str) -> Any:
        resp = self._s3.get_object(Bucket=self.bucket, Key=self._key(key))
        return json.loads(resp["Body"].read().decode("utf-8"))

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(key))

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError:
            return False

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        prefix = f"{self.prefix}/" if self.prefix else ""
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                name = item["Key"]
                if name.endswith(".json"):
                    keys.append(name[len(prefix):-len(".json")])
        return sorted(keys)

    def location(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._key(key)}"


def get_store(config: Config) -> ObjectStore:
    """Construct the object store described by ``config``."""
    if config.store_backend == "s3":
        return S3Store(
            bucket=config.s3_bucket or "",
            prefix=config.s3_prefix,
            endpoint_url=config.s3_endpoint_url,
        )
    if config.store_backend == "local":
        return LocalFileStore(config.resolved_objects_dir())
    raise ValueError(f"Unknown store backend: {config.store_backend!r}")
