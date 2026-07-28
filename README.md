# histo · taskqueue

A small task queue for **AlphaFold Server** job files.

Compose a job from up to **five protein sequence chains**, and the app serialises
it to the exact JSON format the [AlphaFold Server](https://alphafoldserver.com)
ingests, stores the JSON object (local filesystem or S3), and indexes the job
metadata in **DuckDB** so the queue can be listed, filtered and worked through.
The UI uses the [Histo.fyi](https://www.histo.fyi) design system (its stylesheet,
Poppins/Courier Prime typography, and logo).

![Queue](docs/queue.png)

## Features

- **Compose jobs** — 1–5 protein chains (sequence + copy count), a name, and
  optional model seeds. Sequences are validated against the 20 standard amino
  acids.
- **Bulk CSV upload** — submit many jobs at once from a wide-format CSV (one job
  per row); each row is validated and reported individually.
- **pMHC class I panel** — one MHC allele against many peptides, queuing a job
  per peptide (heavy chain + β2-microglobulin + peptide). Backed by a registry of
  **~9,700 HLA-A/B/C alleles** (IMGT/HLA) with type-ahead search; sequences can
  also be pasted directly.
- **AlphaFold Server format** — every job downloads as the canonical
  `[ { "name", "modelSeeds", "sequences", "dialect", "version" } ]` array.
- **Pluggable object store** — `local` filesystem (default) or `s3` (boto3).
- **DuckDB index** — fast listing, status filtering, and per-status counts.
- **Queue lifecycle** — `queued → running → completed | failed`, with a FIFO
  `claim` for workers.
- **JSON API** and a minimal **worker CLI** that drains the queue.

## Tech stack

Python 3.11 · [uv](https://docs.astral.sh/uv/) · Flask · DuckDB · boto3 (optional) · pytest.

## Quick start

```bash
# install dependencies (dev + optional s3 extras)
uv sync --extra dev --extra s3

# run the web app (http://127.0.0.1:8000)
uv run histo-taskqueue

# in another shell: drain the queue with the worker
uv run histo-worker --all
```

Open <http://127.0.0.1:8000>, click **Compose job**, paste up to five sequences,
and queue it. The job detail page shows the exact AlphaFold Server JSON and a
**Download job file** button.

### Configuration

All settings are environment variables (sensible local defaults):

| Variable              | Default                 | Meaning                                   |
|-----------------------|-------------------------|-------------------------------------------|
| `HTQ_STORE_BACKEND`   | `local`                 | `local` or `s3`                           |
| `HTQ_DATA_DIR`        | `data`                  | Base dir for local objects + DuckDB file  |
| `HTQ_OBJECTS_DIR`     | `<data>/objects`        | Local JSON object directory               |
| `HTQ_INDEX_PATH`      | `<data>/index.duckdb`   | DuckDB index file                         |
| `HTQ_S3_BUCKET`       | —                       | Bucket (required for `s3`)                |
| `HTQ_S3_PREFIX`       | `jobs`                  | Key prefix in the bucket                  |
| `HTQ_S3_ENDPOINT_URL` | —                       | Custom endpoint (MinIO / localstack)      |
| `HTQ_ALLELES_PATH`    | bundled                 | JSON registry of MHC class I alleles      |
| `HTQ_API_KEYS_PATH`   | `<data>/api_keys.json`  | API-key store (hashed tokens)             |
| `HTQ_API_AUTH`        | `auto`                  | `auto` / `required` / `disabled`          |
| `HTQ_API_KEY`         | —                       | Bearer token used by the worker           |
| `HTQ_SECRET_KEY`      | `dev-secret-change-me`  | Flask session secret                      |
| `HTQ_SERVER_URL`      | `http://127.0.0.1:8000` | Base URL the worker talks to              |
| `PORT`                | `8000`                  | Web server port                           |

Example with S3:

```bash
HTQ_STORE_BACKEND=s3 HTQ_S3_BUCKET=my-af-jobs uv run histo-taskqueue
```

## AlphaFold Server job format

The downloaded file is an **array of jobs** (so one file can hold several):

```json
[
  {
    "name": "HLA-A*02:01 + NLVPMVATV",
    "modelSeeds": [1, 2],
    "sequences": [
      { "proteinChain": { "sequence": "GSHSMRYFFT...", "count": 1 } },
      { "proteinChain": { "sequence": "NLVPMVATV", "count": 1 } }
    ],
    "dialect": "alphafoldserver",
    "version": 1
  }
]
```

- `modelSeeds` — list of integers; empty ⇒ the server auto-assigns.
- `proteinChain.count` — number of identical copies of that chain.
- `dialect` is always `"alphafoldserver"`, `version` is `1`.

## Bulk CSV upload

Submit many jobs at once from **`/jobs/upload`** with a wide-format CSV — one job
per row (header row required, columns case-insensitive):

| Column                      | Required     | Meaning                              |
|-----------------------------|--------------|--------------------------------------|
| `name`                      | yes          | Job name                             |
| `sequence_1` … `sequence_5` | `sequence_1` | Protein-chain sequences (blank cells skipped) |
| `count_1` … `count_5`       | no           | Copies per chain (default 1)         |
| `model_seeds`               | no           | Comma/space separated integers       |

Each row is validated independently; the results page reports which rows queued
and why any failed. Grab a starter file from **`/jobs/upload/sample.csv`**.

## pMHC class I panel

From **`/jobs/pmhc`**, submit **one MHC class I allele against many peptides** —
the app queues one job per (unique) peptide, each modelled as up to three chains:
the MHC heavy chain, β2-microglobulin, and the peptide.

- Start typing an **allele name** (e.g. `HLA-A*02:01`) — the field autocompletes
  from the registry and fills the heavy chain. Or paste any heavy-chain sequence.
- β2-microglobulin defaults to the human sequence; untick it or supply your own.
- Peptides: one per line (or comma-separated); duplicates are removed.

### Allele registry

The bundled registry (`histo_taskqueue/resources/alleles/registry.json`) holds
**~9,700 HLA-A/B/C alleles** distilled from the IMGT/HLA locus data — each a slim
record:

```json
[
  { "name": "HLA-A*02:01", "locus": "A",
    "heavy_chain": "GSHSMRYFFT…", "pocket_pseudosequence": "YFAMY…" }
]
```

Because there are thousands, the page never renders them all — it queries
`GET /api/alleles?q=` for type-ahead search. Point `HTQ_ALLELES_PATH` at your own
`registry.json` (or a directory containing it plus `human_b2m.json`) to override.

Rebuild the registry from raw IMGT/HLA locus dumps (`hla_a.json`, …):

```bash
python scripts/build_allele_registry.py path/to/locus_dumps
```

## HTTP API

| Method | Path                       | Purpose                               |
|--------|----------------------------|---------------------------------------|
| GET    | `/`                        | Queue dashboard (`?status=` filter)   |
| GET    | `/jobs/new`                | Compose form                          |
| POST   | `/jobs`                    | Create a job (form-encoded)           |
| GET    | `/jobs/upload`             | Bulk CSV upload form                  |
| POST   | `/jobs/upload`             | Create many jobs from CSV             |
| GET    | `/jobs/upload/sample.csv`  | Download a sample CSV                  |
| GET    | `/jobs/pmhc`               | pMHC class I panel form               |
| POST   | `/jobs/pmhc`               | Queue one job per peptide             |
| GET    | `/api/alleles?q=`          | Type-ahead allele search (JSON)       |
| GET    | `/jobs/<id>`               | Job detail                            |
| GET    | `/jobs/<id>/download`      | Download the AlphaFold job file       |
| POST   | `/jobs/<id>/status`        | Set status (form)                     |
| POST   | `/jobs/<id>/delete`        | Delete a job                          |
| POST   | `/api/jobs` (JSON)         | Create a job — needs `create` scope   |
| POST   | `/api/jobs/pmhc`           | Queue a pMHC panel — `create` scope   |
| POST   | `/api/jobs/bulk`           | Create jobs from CSV — `create` scope |
| GET    | `/api/whoami`              | Identify the calling key              |
| GET    | `/api/jobs`                | List jobs + counts (JSON)             |
| GET    | `/api/jobs/<id>`           | Job record + file (JSON)              |
| POST   | `/api/jobs/claim`          | FIFO claim next queued job → running  |
| POST   | `/api/jobs/<id>/status`    | Set status (JSON)                     |
| GET    | `/healthz`                 | Health check                          |

## API keys & authentication

The JSON API (`/api/*`) is protected by **token-based API keys with scopes**:

- `create` — create jobs (producers).
- `consume` — list jobs, claim the queue, set status (workers/consumers).
- `admin` — grants all scopes (reserved for future privileged operations).

Keys are bearer tokens (`htq_…`); only their SHA-256 hash is stored (in
`HTQ_API_KEYS_PATH`). Present one as `Authorization: Bearer <token>` (or
`X-API-Key: <token>`). Manage them with the CLI:

```bash
uv run histo-taskqueue-keys create --label "prod worker" --scopes consume
uv run histo-taskqueue-keys create --label "pipeline" --scopes create
uv run histo-taskqueue-keys list
uv run histo-taskqueue-keys revoke <id>
```

The token is printed **once** at creation — store it immediately.

**Enforcement** is controlled by `HTQ_API_AUTH`:

- `auto` (default) — the API is open until the first key exists, then enforced.
- `required` — always enforced (return 401 without a valid key).
- `disabled` — never enforced (local development).

The HTML UI (`/`, `/jobs/*`) is unauthenticated and intended for trusted/local
use; lock down programmatic access via the API + keys.

## Worker

The Flask app is the single owner of the DuckDB index (DuckDB allows only one
read-write process at a time), so the worker talks to the **running app** over
its JSON API:

```bash
uv run histo-worker            # claim + process one job
uv run histo-worker --all      # drain the whole queue
uv run histo-worker --list     # print queue counts
uv run histo-worker --url http://host:8000 --api-key htq_…   # or set HTQ_API_KEY
```

The bundled worker is a stand-in — it validates the stored job file and marks the
job `completed`. Real AlphaFold execution is out of scope for v1 (see `PLAN.md`).

## Architecture

```
histo_taskqueue/
  config.py     Environment-driven configuration
  alphafold.py  Validate chains + build/parse AlphaFold Server job JSON
  bulk.py       Wide-format CSV parsing into job specs
  pmhc.py       pMHC class I panel builder (allele × peptides) + default β2m
  alleles.py    AlleleRegistry — load slim registry, search, default β2m
  apikeys.py    Scoped API keys — hashed token store, verify, scopes
  manage.py     histo-taskqueue-keys CLI (create / list / revoke)
  store.py      ObjectStore interface; LocalFileStore + S3Store
  index.py      JobIndex — DuckDB schema, upsert, list/filter, counts
  queue.py      JobQueue — create / get / claim / set_status / delete
  app.py        Flask app factory + routes
  templates/    base · _logo · index · new · upload · pmhc · bulk_results · detail
  static/css/   histo-site.css (Histo design system) + app.css
  static/js/    allele-autocomplete.js
  resources/alleles/  registry.json (~9,700 alleles) + human_b2m.json
scripts/        build_allele_registry.py (IMGT dumps → slim registry)
worker.py       HTTP worker CLI
```

The object store is the **source of truth** (it holds the full job files); the
DuckDB index holds queryable metadata and can be rebuilt from the store.

## Development

```bash
uv sync --extra dev
uv run pytest        # 68 tests: unit + Flask route integration
```

## License

MIT — see `LICENSE`.
