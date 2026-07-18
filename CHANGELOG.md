# Changelog

All notable changes to **histo · taskqueue** are documented here. This project
adheres to [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-07-18

Initial release: a working AlphaFold Server job task queue.

### Added

- **Project scaffolding** — `uv`-managed `pyproject.toml` (Flask + DuckDB core,
  optional `s3`/`dev` extras), `histo-taskqueue` and `histo-worker` console
  scripts, and a `PLAN.md` design document.
- **`alphafold.py`** — `ProteinChain` model plus validation (20 standard amino
  acids, 1–5 chains, copy counts, model seeds) and a builder that emits the exact
  AlphaFold Server job file: an array of `{ name, modelSeeds, sequences,
  dialect: "alphafoldserver", version: 1 }`.
- **`store.py`** — pluggable JSON object store with a `LocalFileStore` (atomic
  writes) and an `S3Store` (boto3), selected via config.
- **`index.py`** — DuckDB-backed `JobIndex`: schema, upsert, get, list (with
  status filter), FIFO `next_queued`, and per-status counts.
- **`queue.py`** — `JobQueue` tying the store and index together: create, get,
  list, `claim_next` (FIFO → `running`), `set_status`, and delete.
- **`app.py`** — Flask app factory with the queue dashboard, a 5-chain compose
  form, job detail (pretty JSON + status controls), a download endpoint serving
  the AlphaFold job file, and a JSON API (`/api/jobs`, `/api/jobs/claim`,
  `/api/jobs/<id>/status`) plus `/healthz`.
- **UI** — Jinja templates (`base`, `index`, `new`, `detail`) and a Histo.fyi-style
  stylesheet (`histo.css`): warm off-white canvas, teal accent, cards,
  colour-coded status badges, responsive layout.
- **`worker.py`** — a minimal HTTP worker CLI that claims queued jobs from the
  running app and advances them to `completed`/`failed` (`--all`, `--list`,
  `--url`). It talks over the API because the Flask app is the single owner of
  the DuckDB index.
- **Tests** — 31 pytest tests covering the AlphaFold builder/validation, the
  local store, the queue lifecycle (create → claim → complete → delete), and the
  full HTTP flow via the Flask test client.
- **Docs** — `README.md` (quick start, config, API, format reference) with
  screenshots under `docs/`.

### Notes

- The worker is a stand-in; real AlphaFold execution is out of scope for v1.
- DuckDB permits a single read-write process, so run one web app instance and let
  workers reach it over HTTP.
