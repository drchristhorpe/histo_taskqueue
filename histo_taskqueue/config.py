"""Configuration for histo_taskqueue, sourced from environment variables.

All settings have sensible local-first defaults so the app runs with zero
configuration. Set ``HTQ_STORE_BACKEND=s3`` (plus the ``HTQ_S3_*`` vars) to use
S3 instead of the local filesystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Config:
    """Runtime configuration.

    Attributes:
        store_backend: ``"local"`` or ``"s3"``.
        data_dir: Base directory for local storage (JSON objects + DuckDB file).
        objects_dir: Where local JSON objects live (defaults to ``data_dir/objects``).
        index_path: DuckDB database file (defaults to ``data_dir/index.duckdb``).
        s3_bucket: Bucket name for the S3 backend.
        s3_prefix: Key prefix for objects in the S3 bucket.
        s3_endpoint_url: Optional custom endpoint (e.g. MinIO / localstack).
        secret_key: Flask session secret.
    """

    store_backend: str = "local"
    data_dir: Path = Path("data")
    objects_dir: Path | None = None
    index_path: Path | None = None
    s3_bucket: str | None = None
    s3_prefix: str = "jobs"
    s3_endpoint_url: str | None = None
    alleles_path: Path | None = None
    api_keys_path: Path | None = None
    api_auth_mode: str = "auto"  # "auto" | "required" | "disabled"
    secret_key: str = "dev-secret-change-me"

    def resolved_objects_dir(self) -> Path:
        return self.objects_dir or (self.data_dir / "objects")

    def resolved_index_path(self) -> Path:
        return self.index_path or (self.data_dir / "index.duckdb")

    def resolved_api_keys_path(self) -> Path:
        return self.api_keys_path or (self.data_dir / "api_keys.json")

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = Path(_env("HTQ_DATA_DIR", "data"))
        objects_dir = os.environ.get("HTQ_OBJECTS_DIR")
        index_path = os.environ.get("HTQ_INDEX_PATH")
        alleles_path = os.environ.get("HTQ_ALLELES_PATH")
        api_keys_path = os.environ.get("HTQ_API_KEYS_PATH")
        return cls(
            store_backend=_env("HTQ_STORE_BACKEND", "local").lower(),
            data_dir=data_dir,
            objects_dir=Path(objects_dir) if objects_dir else None,
            index_path=Path(index_path) if index_path else None,
            s3_bucket=os.environ.get("HTQ_S3_BUCKET"),
            s3_prefix=_env("HTQ_S3_PREFIX", "jobs"),
            s3_endpoint_url=os.environ.get("HTQ_S3_ENDPOINT_URL"),
            alleles_path=Path(alleles_path) if alleles_path else None,
            api_keys_path=Path(api_keys_path) if api_keys_path else None,
            api_auth_mode=_env("HTQ_API_AUTH", "auto").lower(),
            secret_key=_env("HTQ_SECRET_KEY", "dev-secret-change-me"),
        )
