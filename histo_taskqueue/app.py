"""Flask application factory and routes for histo_taskqueue."""

from __future__ import annotations

import json

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from . import alphafold
from .config import Config
from .index import STATUSES, JobIndex
from .queue import JobQueue
from .store import get_store

MAX_CHAINS = alphafold.MAX_CHAINS


def create_app(config: Config | None = None) -> Flask:
    """Build a configured Flask app.

    A single :class:`JobQueue` (store + DuckDB index) is attached to the app and
    shared across requests. The dev server is run single-threaded so the one
    DuckDB connection is never used concurrently.
    """
    config = config or Config.from_env()
    app = Flask(__name__)
    app.secret_key = config.secret_key
    app.config["HTQ_CONFIG"] = config

    store = get_store(config)
    index = JobIndex(config.resolved_index_path())
    queue = JobQueue(store, index)
    app.extensions["htq_queue"] = queue

    def q() -> JobQueue:
        return app.extensions["htq_queue"]

    # -- views -------------------------------------------------------------
    @app.route("/")
    def index_view():
        status = request.args.get("status") or None
        if status and status not in STATUSES:
            status = None
        jobs = q().list(status)
        return render_template(
            "index.html",
            jobs=jobs,
            counts=q().counts(),
            statuses=STATUSES,
            active_status=status,
        )

    @app.route("/jobs/new")
    def new_job_view():
        return render_template(
            "new.html", max_chains=MAX_CHAINS, form=None, chain_range=range(1, MAX_CHAINS + 1)
        )

    @app.route("/jobs", methods=["POST"])
    def create_job():
        name = request.form.get("name", "")
        seeds_raw = request.form.get("model_seeds", "")

        chains: list[alphafold.ProteinChain] = []
        for i in range(1, MAX_CHAINS + 1):
            seq = request.form.get(f"sequence_{i}", "")
            if not seq or not seq.strip():
                continue
            count_raw = request.form.get(f"count_{i}", "1").strip() or "1"
            try:
                count = int(count_raw)
            except ValueError:
                flash(f"Chain {i}: copies must be a whole number.", "error")
                return _rerender_new(request.form)
            chains.append(alphafold.ProteinChain(sequence=seq, count=count))

        try:
            seeds = alphafold.parse_model_seeds(seeds_raw)
            record = q().create(name, chains, seeds)
        except alphafold.ValidationError as exc:
            flash(str(exc), "error")
            return _rerender_new(request.form)

        flash(f"Job '{record.name}' queued.", "success")
        return redirect(url_for("job_detail", job_id=record.id))

    def _rerender_new(form) -> str:
        return render_template(
            "new.html",
            max_chains=MAX_CHAINS,
            form=form,
            chain_range=range(1, MAX_CHAINS + 1),
        )

    @app.route("/jobs/<job_id>")
    def job_detail(job_id: str):
        record = q().get(job_id)
        if record is None:
            abort(404)
        job_file = q().get_job_file(job_id)
        pretty = json.dumps(job_file, indent=2)
        return render_template(
            "detail.html",
            job=record,
            pretty_json=pretty,
            statuses=STATUSES,
        )

    @app.route("/jobs/<job_id>/download")
    def download_job(job_id: str):
        record = q().get(job_id)
        if record is None:
            abort(404)
        job_file = q().get_job_file(job_id)
        body = json.dumps(job_file, indent=2)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in record.name)
        filename = f"{safe or 'job'}_{job_id}.json"
        return Response(
            body,
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/jobs/<job_id>/status", methods=["POST"])
    def update_status(job_id: str):
        status = request.form.get("status", "")
        if status not in STATUSES:
            flash(f"Unknown status: {status}", "error")
            return redirect(url_for("job_detail", job_id=job_id))
        record = q().set_status(job_id, status)
        if record is None:
            abort(404)
        flash(f"Status set to {status}.", "success")
        return redirect(url_for("job_detail", job_id=job_id))

    @app.route("/jobs/<job_id>/delete", methods=["POST"])
    def delete_job(job_id: str):
        if not q().delete(job_id):
            abort(404)
        flash("Job deleted.", "success")
        return redirect(url_for("index_view"))

    # -- json api ----------------------------------------------------------
    @app.route("/api/jobs")
    def api_list():
        status = request.args.get("status") or None
        jobs = [r.as_dict() for r in q().list(status)]
        return {"jobs": jobs, "counts": q().counts()}

    @app.route("/api/jobs/<job_id>")
    def api_get(job_id: str):
        record = q().get(job_id)
        if record is None:
            abort(404)
        return {"job": record.as_dict(), "file": q().get_job_file(job_id)}

    @app.route("/api/jobs/claim", methods=["POST"])
    def api_claim():
        record = q().claim_next()
        if record is None:
            return {"job": None}, 204
        return {"job": record.as_dict(), "file": q().get_job_file(record.id)}

    @app.route("/api/jobs/<job_id>/status", methods=["POST"])
    def api_set_status(job_id: str):
        payload = request.get_json(silent=True) or request.form
        status = (payload.get("status") or "").strip()
        if status not in STATUSES:
            return {"error": f"Unknown status: {status!r}", "allowed": list(STATUSES)}, 400
        record = q().set_status(job_id, status)
        if record is None:
            abort(404)
        return {"job": record.as_dict()}

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "backend": config.store_backend}

    return app


def main() -> None:  # pragma: no cover - entry point
    import os

    app = create_app()
    port = int(os.environ.get("PORT", "8000"))
    # Single-threaded: the one DuckDB connection is not shared across threads.
    app.run(host="127.0.0.1", port=port, threaded=False)


if __name__ == "__main__":  # pragma: no cover
    main()
