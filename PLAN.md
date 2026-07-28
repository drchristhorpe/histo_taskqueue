# PLAN — histo_taskqueue

A task queue for **AlphaFold Server** job files. Users compose a job from up to
five protein sequence chains; the app serialises it to the exact JSON format the
AlphaFold Server ingests, stores the JSON object (local file store or S3), and
indexes job metadata in DuckDB so the queue can be listed, filtered and worked
through.

## Goals

- Compose an AlphaFold Server job from **up to 5 protein chains** (sequence +
  number of copies each), a job name, and optional model seeds.
- Persist each job as a JSON object in a pluggable **object store**
  (`local` filesystem by default, `s3` optional via boto3).
- Maintain a **DuckDB index** of job metadata (id, name, status, chain summary,
  timestamps) for fast listing / filtering / stats — the store holds the source
  of truth (the JSON), DuckDB is a rebuildable index.
- Provide a **queue lifecycle**: `queued → running → completed | failed`, with a
  FIFO `claim` operation so a worker can pull the next job.
- Download the canonical AlphaFold Server job file (`[ { ... } ]`) for any job.
- A web UI styled to echo **Histo.fyi** (clean, typographic, muted palette).

## Tech stack

- **Python 3.11**, managed with **uv** (`pyproject.toml` + `uv.lock`).
- **Flask** for the web app (app-factory pattern for testability).
- **DuckDB** for the index.
- **boto3** (optional) for the S3 object store backend.
- **pytest** for tests.

> Flask (not Quart) was chosen: the workload is I/O-light request/response with a
> synchronous DuckDB driver, and Flask's test client keeps the test suite simple.
> The storage and queue layers are framework-agnostic, so swapping is cheap.

## AlphaFold Server job JSON format

Top level is an **array of jobs** so one file can hold several. Each job:

```json
[
  {
    "name": "My job",
    "modelSeeds": [],
    "sequences": [
      { "proteinChain": { "sequence": "MVLSPADKTNV", "count": 1 } }
    ],
    "dialect": "alphafoldserver",
    "version": 1
  }
]
```

- `name` — free text.
- `modelSeeds` — array of integers; empty means the server auto-assigns.
- `sequences` — array of entities; here `proteinChain` with `sequence` (upper-case
  one-letter amino acids) and `count` (copies). `glycans` / `modifications` are
  supported by the builder but optional and omitted when empty.
- `dialect` — always `"alphafoldserver"`; `version` — `1`.

## Architecture / modules

```
histo_taskqueue/
  config.py       Config from environment (backend, data dir, duckdb path, S3)
  alphafold.py    Validate chains + build/parse the AlphaFold Server job JSON
  store.py        ObjectStore interface; LocalFileStore + S3Store; get_store()
  index.py        JobIndex — DuckDB schema, upsert, list/filter, stats, rebuild
  queue.py        JobQueue — ties store+index: create, get, claim, set_status, delete
  app.py          Flask app factory + routes + Jinja templates
  templates/      base / index (queue) / new (compose) / detail
  static/css/     histo.css (Histo-style stylesheet)
worker.py         CLI worker: claim next job, simulate run, mark complete
tests/            alphafold, store, index, queue, app (route) tests
```

### Routes

| Method | Path                    | Purpose                                  |
|--------|-------------------------|------------------------------------------|
| GET    | `/`                     | Queue dashboard (list + status filter)   |
| GET    | `/jobs/new`             | Compose form (5 chain slots)             |
| POST   | `/jobs`                 | Validate, build JSON, store, enqueue     |
| GET    | `/jobs/<id>`            | Job detail + pretty JSON                 |
| GET    | `/jobs/<id>/download`   | Download AlphaFold job file              |
| POST   | `/jobs/<id>/status`     | Set status (queued/running/completed/failed) |
| POST   | `/jobs/<id>/delete`     | Delete job (store + index)               |
| POST   | `/api/jobs/claim`       | FIFO claim next queued job → running     |
| GET    | `/api/jobs`             | JSON listing (for tooling/worker)        |
| GET    | `/healthz`              | Health check                             |

## Validation rules

- 1–5 protein chains; at least one non-empty chain required.
- Sequence: strip whitespace, upper-case; must be non-empty and contain only the
  20 standard amino acids `ACDEFGHIKLMNPQRSTVWY`.
- `count` (copies): integer ≥ 1 (default 1).
- Model seeds: optional comma/space separated integers; empty ⇒ `[]`.

## Steps

1. Scaffold: `pyproject.toml`, package dirs, `uv sync`.
2. `config.py`, `alphafold.py` (builder + validation) + tests.
3. `store.py` (local + s3) + tests.
4. `index.py` (DuckDB) + tests.
5. `queue.py` (create/claim/status/delete) + tests.
6. `app.py` routes + Jinja templates + `histo.css`.
7. `worker.py` CLI.
8. Route/integration tests; run the full suite.
9. Manual smoke test (start server, create + claim + download a job).
10. Docs: README.md, CHANGELOG.md; commit and push.

## Testing

- Unit: AlphaFold builder/validation, store roundtrip, index upsert/list/stats,
  queue lifecycle (create → claim → complete).
- Integration: Flask test client drives the full HTTP flow against temp dirs and
  an in-memory/temp DuckDB.
- Manual: launch app, submit a job, verify JSON download matches the schema.

## Bulk & pMHC extensions

Two batch-submission flows layered on the same store + index:

- **Bulk CSV upload** (`bulk.py`, `/jobs/upload`) — a wide-format CSV, one job per
  row (`name`, `sequence_1..5`, `count_1..5`, `model_seeds`). Rows parse into
  `alphafold.JobSpec`s, are validated individually, and queued via
  `JobQueue.create_spec`; a results page reports per-row outcomes.
- **pMHC class I panel** (`pmhc.py`, `/jobs/pmhc`) — one MHC allele × many
  peptides ⇒ one job per unique peptide, each `[heavy chain, β2m, peptide]`. β2m
  defaults to the human sequence. Heavy-chain sequences come from a pasted value
  or an **allele registry** (`alleles.py`, JSON via `HTQ_ALLELES_PATH`).

Both reuse `alphafold.JobSpec` and the existing validation/build path, so the
canonical AlphaFold Server output is identical to single-job submission.

## Styling & allele data

- **Histo design system** — the app serves the real histo.fyi stylesheet
  (`static/css/histo-site.css`) plus `app.css` for app-specific components, the
  Histo logo partial (`_logo.html`), and Poppins/Courier Prime via Google Fonts.
  Templates follow Histo's `section > grid-container > column-full-width > inner`
  layout with `.button`, `.text-input`, and `.phase-label`-style status badges.
- **Allele registry** — `resources/alleles/registry.json` carries ~9,700
  HLA-A/B/C alleles distilled from the IMGT/HLA locus dumps by
  `scripts/build_allele_registry.py` (kept slim: name, locus, canonical heavy
  chain, pocket pseudosequence). Too many for a `<select>`, so the pMHC page uses
  a `GET /api/alleles?q=` search endpoint with a JS type-ahead; the heavy chain is
  resolved from the registry server-side on submit. β2m defaults to
  `human_b2m.json`.

## API keys & programmatic access

- **Scoped bearer tokens** (`apikeys.py`) gate the JSON API: `create` (produce),
  `consume` (list/claim/status), `admin` (all). Only SHA-256 hashes are stored;
  the `histo-taskqueue-keys` CLI issues/lists/revokes them. `HTQ_API_AUTH`
  chooses enforcement (`auto`/`required`/`disabled`).
- **Creation API** — `POST /api/jobs`, `/api/jobs/pmhc`, `/api/jobs/bulk` mirror
  the HTML flows for machine clients; consume endpoints require `consume`. This
  is the surface the (separate) client library and CLI talk to — the client is a
  thin, API-only package so other Histo products can produce/consume jobs without
  the server stack.

## Out of scope (v1)

- Real AlphaFold execution / GPU submission (worker only simulates state).
- Auth / multi-user accounts.
- DNA/RNA/ligand/ion entities in the UI (builder leaves room; UI is protein-only).
