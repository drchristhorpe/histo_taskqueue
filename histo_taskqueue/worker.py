"""A minimal queue worker CLI.

The Flask app is the single owner of the DuckDB index (DuckDB permits only one
read-write process at a time), so the worker talks to the *running app* over its
JSON API rather than opening the index directly. It claims the next queued job
(FIFO), "runs" it (a stand-in — real AlphaFold execution is out of scope for v1),
and marks it completed or failed.

Usage:
    uv run histo-worker                 # claim and process one job
    uv run histo-worker --all           # drain the whole queue
    uv run histo-worker --list          # show current queue counts
    uv run histo-worker --url http://host:8000

The server URL defaults to ``$HTQ_SERVER_URL`` or ``http://127.0.0.1:8000``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


class WorkerError(RuntimeError):
    pass


def _request(url: str, method: str = "GET", data: dict | None = None,
             api_key: str | None = None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise WorkerError(
                f"Authentication failed ({exc.code}). Set --api-key / HTQ_API_KEY "
                "to a key with the 'consume' scope."
            ) from exc
        raise WorkerError(f"Server error {exc.code} at {url}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network dependent
        raise WorkerError(f"Could not reach the server at {url}: {exc}") from exc


def claim_next(base_url: str, api_key: str | None = None) -> dict | None:
    return _request(f"{base_url}/api/jobs/claim", method="POST", api_key=api_key)


def set_status(base_url: str, job_id: str, status: str, api_key: str | None = None) -> dict:
    return _request(
        f"{base_url}/api/jobs/{job_id}/status", method="POST",
        data={"status": status}, api_key=api_key,
    )


def counts(base_url: str, api_key: str | None = None) -> dict:
    return _request(f"{base_url}/api/jobs", api_key=api_key)["counts"]


def process_one(base_url: str, api_key: str | None = None) -> bool:
    """Claim and process one job. Returns True if a job was processed."""
    claimed = claim_next(base_url, api_key)
    if not claimed or not claimed.get("job"):
        print("Queue empty — nothing to claim.")
        return False
    job = claimed["job"]
    print(f"Claimed {job['id']} — {job['name']} ({job['chain_summary']})")
    try:
        job_file = claimed["file"]
        assert isinstance(job_file, list) and job_file, "job file must be a non-empty array"
        set_status(base_url, job["id"], "completed", api_key)
        print(f"Completed {job['id']}")
    except WorkerError:
        raise
    except Exception as exc:  # noqa: BLE001 - report any failure onto the job
        set_status(base_url, job["id"], "failed", api_key)
        print(f"Failed {job['id']}: {exc}", file=sys.stderr)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="histo_taskqueue worker")
    parser.add_argument("--all", action="store_true", help="drain the whole queue")
    parser.add_argument("--list", action="store_true", help="print queue counts and exit")
    parser.add_argument(
        "--url",
        default=os.environ.get("HTQ_SERVER_URL", "http://127.0.0.1:8000"),
        help="base URL of the running histo_taskqueue app",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("HTQ_API_KEY"),
        help="API key with the 'consume' scope (or set HTQ_API_KEY)",
    )
    args = parser.parse_args()
    base_url = args.url.rstrip("/")
    api_key = args.api_key

    try:
        if args.list:
            for status, n in counts(base_url, api_key).items():
                print(f"{status:>10}: {n}")
            return

        if args.all:
            processed = 0
            while process_one(base_url, api_key):
                processed += 1
            print(f"Done — processed {processed} job(s).")
        else:
            process_one(base_url, api_key)
    except WorkerError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
