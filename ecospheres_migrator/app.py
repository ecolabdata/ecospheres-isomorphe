import io
import os

from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, send_file, session, abort, redirect, url_for

from ecospheres_migrator.queue import get_queue, get_job
from ecospheres_migrator.migrator import Migrator

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "default-secret-key")


@app.route("/")
def select():
    return render_template(
        "select.html.j2",
        url=session.get("url", ""),
        transformations=Migrator.list_transformations(Path(app.root_path, "transformations"))
    )


@app.route("/select/preview", methods=["POST"])
def select_preview():
    url = request.form.get("url")
    if not url:
        return "Veuillez entrer une URL de catalogue"
    query = request.form.get("query")
    if not query:
        return "Veuillez entrer une requête de recherche"
    migrator = Migrator(url=url)
    results = migrator.select(query=query)
    return render_template("fragments/select_preview.html.j2", results=results)


@app.route("/transform", methods=["POST"])
def transform():
    url = request.form.get("url")
    if not url:
        abort(400, 'Missing `url` parameter')
    session["url"] = url
    query = request.form.get("query")
    if not query:
        abort(400, 'Missing `query` parameter')
    transformation = request.form.get("transformation")
    if not transformation:
        abort(400, 'Missing `transformation` parameter')
    migrator = Migrator(url=url)
    selection = migrator.select(query=query)
    job = get_queue().enqueue(migrator.transform, transformation, selection)
    return redirect(url_for("transform_success", job_id=job.id))


@app.route("/transform/success/<job_id>")
def transform_success(job_id):
    job = get_job(job_id)
    if not job:
        abort(404)
    return render_template(
        "transform.html.j2",
        job=job,
    )


@app.route("/transform/job_status/<job_id>")
def transform_job_status(job_id: str):
    return render_template(
        "fragments/transform_job_status.html.j2",
        job=get_job(job_id),
        now=datetime.now().isoformat(timespec="seconds"),
        url=session["url"],
    )


@app.route("/transform/download_result/<job_id>")
def transform_download_result(job_id: str):
    job = get_job(job_id)
    return send_file(
        io.BytesIO(job.result),
        mimetype="application/zip",
        download_name=f"{job_id}.zip",
        as_attachment=True,
    )


@app.route("/migrate/<job_id>", methods=["POST"])
def migrate(job_id: str):
    transform_job = get_job(job_id)
    if not transform_job:
        abort(404)
    username = request.form.get("username")
    password = request.form.get("password")
    migrator = Migrator(url=session["url"], username=username, password=password)
    migrate_job = get_queue().enqueue(migrator.migrate, transform_job.result)
    return redirect(url_for("migrate_success", job_id=migrate_job.id))


@app.route("/migrate/success/<job_id>")
def migrate_success(job_id: str):
    job = get_job(job_id)
    if not job:
        abort(404)
    return render_template("migrate.html.j2", job=job)


@app.route("/migrate/job_status/<job_id>")
def migrate_job_status(job_id: str):
    return render_template(
        "fragments/migrate_job_status.html.j2",
        job=get_job(job_id),
        now=datetime.now().isoformat(timespec="seconds"),
    )


@app.route("/docs")
def documentation():
    return render_template("documentation.html.j2")


if __name__ == '__main__':
    app.run(debug=True)
