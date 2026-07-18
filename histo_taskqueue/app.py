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

from . import alphafold, bulk, pmhc
from .alleles import AlleleRegistry
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
    app.extensions["htq_alleles"] = AlleleRegistry(config.alleles_path)

    def q() -> JobQueue:
        return app.extensions["htq_queue"]

    def alleles() -> AlleleRegistry:
        return app.extensions["htq_alleles"]

    def _create_specs(specs) -> tuple[list[bulk.RowResult], int]:
        """Create a list of RowResults' specs, filling in job_id/error. Returns
        (results, created_count)."""
        created = 0
        for r in specs:
            if r.spec is None:
                continue
            try:
                record = q().create_spec(r.spec)
                r.job_id = record.id
                created += 1
            except alphafold.ValidationError as exc:
                r.error = str(exc)
        return specs, created

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

    # -- bulk CSV upload ---------------------------------------------------
    @app.route("/jobs/upload")
    def upload_view():
        return render_template("upload.html")

    @app.route("/jobs/upload/sample.csv")
    def upload_sample():
        return Response(
            bulk.SAMPLE_CSV,
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="jobs_sample.csv"'},
        )

    @app.route("/jobs/upload", methods=["POST"])
    def upload_jobs():
        text = ""
        upload = request.files.get("file")
        if upload and upload.filename:
            text = upload.read().decode("utf-8", errors="replace")
        if not text.strip():
            text = request.form.get("csv_text", "")
        if not text.strip():
            flash("Provide a CSV file or paste CSV text.", "error")
            return render_template("upload.html")

        try:
            parsed = bulk.parse_jobs_csv(text)
        except alphafold.ValidationError as exc:
            flash(str(exc), "error")
            return render_template("upload.html")

        if not parsed:
            flash("No data rows found in the CSV.", "error")
            return render_template("upload.html")

        results, created = _create_specs(parsed)
        flash(f"Created {created} of {len(results)} job(s).",
              "success" if created else "error")
        return render_template(
            "bulk_results.html", results=results, created=created,
            total=len(results), kind="CSV upload",
        )

    # -- pMHC class I panel ------------------------------------------------
    @app.route("/jobs/pmhc")
    def pmhc_view():
        return render_template(
            "pmhc.html", alleles=alleles().list(), default_b2m=pmhc.DEFAULT_B2M, form=None
        )

    @app.route("/jobs/pmhc", methods=["POST"])
    def pmhc_submit():
        form = request.form
        allele_name = form.get("allele_name", "").strip()
        heavy_chain = form.get("heavy_chain", "")
        b2m = form.get("b2m", "")
        include_b2m = form.get("include_b2m") == "on"

        # If a registered allele was chosen and no custom heavy chain was typed,
        # fill the sequences from the registry.
        selected = form.get("allele_select", "").strip()
        if selected:
            allele = alleles().get(selected)
            if allele:
                if not allele_name:
                    allele_name = allele.name
                if not heavy_chain.strip():
                    heavy_chain = allele.heavy_chain
                if not b2m.strip() and allele.b2m:
                    b2m = allele.b2m

        peptides = pmhc.parse_peptides(form.get("peptides", ""))
        try:
            specs = pmhc.build_pmhc_specs(
                allele_name=allele_name,
                heavy_chain=heavy_chain,
                peptides=peptides,
                b2m=b2m or None,
                include_b2m=include_b2m,
            )
        except alphafold.ValidationError as exc:
            flash(str(exc), "error")
            return render_template(
                "pmhc.html", alleles=alleles().list(),
                default_b2m=pmhc.DEFAULT_B2M, form=form,
            )

        rows = [
            bulk.RowResult(row_num=i, name=s.name, spec=s)
            for i, s in enumerate(specs, start=1)
        ]
        results, created = _create_specs(rows)
        flash(f"Created {created} of {len(results)} pMHC job(s).",
              "success" if created else "error")
        return render_template(
            "bulk_results.html", results=results, created=created,
            total=len(results), kind=f"pMHC panel — {allele_name}",
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
