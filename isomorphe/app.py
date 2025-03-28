import difflib
import io
import logging
import os
from datetime import datetime
from pathlib import Path

import requests
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from isomorphe.auth import authenticated, connection_infos
from isomorphe.batch import (
    MigrateMode,
    SkipReasonMessage,
    SuccessTransformBatchRecord,
    TransformBatchRecord,
)
from isomorphe.geonetwork import GeonetworkConnectionError
from isomorphe.migrator import Migrator
from isomorphe.rqueue import get_job, get_queue
from isomorphe.util import render_markdown

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "default-secret-key")
app.config["TRANSFORM_TIMEOUT"] = 3 * 60 * 60  # 3 hours
app.config["TRANSFORM_TTL"] = 60 * 60 * 24 * 7 * 30 * 2  # 2 months
app.config["MIGRATE_TIMEOUT"] = 3 * 60 * 60  # 3 hours
app.config["MIGRATE_TTL"] = 60 * 60 * 24 * 7 * 30 * 2  # 2 months
app.config["TRANSFORMATIONS_PATH"] = (
    Path(os.getenv("TRANSFORMATIONS_PATH", ""))
    if os.getenv("TRANSFORMATIONS_PATH")
    else Path(app.root_path, "transformations/default")
)

logging.basicConfig(level=logging.DEBUG if app.debug else logging.INFO)


@app.route("/")
def login_form():
    return render_template(
        "login.html.j2",
        url=session.get("url", ""),
        username=session.get("username", ""),
        password=session.get("password", ""),
    )


@app.route("/login", methods=["POST"])
def login():
    url = request.form.get("url")
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password or not url:
        abort(400, "Missing login parameter(s)")

    try:
        migrator = Migrator(url=url, username=username, password=password)
        gn_info = migrator.gn.info()
    except (requests.exceptions.RequestException, GeonetworkConnectionError) as e:
        flash(f"Problème d'authentification ({e})", "error")
        # still record the login info for the next try
        session["url"] = url.rstrip("/")
        session["username"] = username
        session["password"] = password
        return redirect(url_for("login_form"))
    else:
        authenticated = gn_info.get("me", {}).get("@authenticated", "false") == "true"
        if not authenticated:
            flash("Problème d'authentification (retour api geonetwork)", "error")
            return redirect(url_for("login_form"))

    session["url"] = url.rstrip("/")
    session["username"] = username
    session["password"] = password
    return redirect(url_for("select"))


@app.route("/select")
@authenticated()
def select():
    url, username, password = connection_infos()
    migrator = Migrator(url=url, username=username, password=password)
    sources = sorted(
        [{"id": k, "name": v} for k, v in migrator.gn.get_sources().items()],
        key=lambda x: x["name"].casefold(),
    )
    return render_template(
        "select.html.j2",
        url=session.get("url", ""),
        version=migrator.geonetwork_version,
        transformations=Migrator.list_transformations(app.config["TRANSFORMATIONS_PATH"]),
        sources=sources,
        groups=migrator.gn.get_groups(),
    )


@app.route("/select_transformation")
def select_transformation():
    transformation = request.args.get("transformation")
    if not transformation:
        abort(400, "Missing `transformation` parameter")
    transformation = Migrator.get_transformation(transformation, app.config["TRANSFORMATIONS_PATH"])
    return render_template("fragments/select_transformation.html.j2", transformation=transformation)


def _get_filters(form):
    return {
        field.removeprefix("filter-"): value
        for field, value in form.items()
        if field.startswith("filter-") and value not in (None, "")
    }


@app.route("/select/preview", methods=["POST"])
@authenticated(redirect=False)
def select_preview():
    url, username, password = connection_infos()
    if not url:
        return "<em>Veuillez entrer une URL de catalogue.</em>"
    filters = _get_filters(request.form)
    migrator = Migrator(url=url, username=username, password=password)
    results = migrator.select(filters=filters)
    return render_template("fragments/select_preview.html.j2", results=results, url=url)


@app.route("/transform", methods=["POST"])
@authenticated()
def transform():
    url, username, password = connection_infos()
    filters = _get_filters(request.form)
    transformation = request.form.get("transformation")
    if not transformation:
        abort(400, "Missing `transformation` parameter")
    transformation = Migrator.get_transformation(transformation, app.config["TRANSFORMATIONS_PATH"])
    transformation_params = {}
    for param in transformation.params:
        form_param_name = f"param-{param.name}"
        if form_param_name not in request.form:
            abort(400, f"Missing `{param.name}` parameter for transformation")
        transformation_params[param.name] = request.form.get(form_param_name)
    migrator = Migrator(url=url, username=username, password=password)
    selection = migrator.select(filters=filters)
    job = get_queue().enqueue(
        migrator.transform,
        transformation,
        selection,
        transformation_params=transformation_params,
        job_timeout=app.config["TRANSFORM_TIMEOUT"],
        result_ttl=app.config["TRANSFORM_TTL"],
    )
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


@app.route("/transform/success/<job_id>/result/<uuid>")
def transform_result(job_id: str, uuid: str):
    job = get_job(job_id)
    if not job or not job.result:
        abort(404)
    result: SuccessTransformBatchRecord | None = next(
        (j for j in job.result.successes() if j.uuid == uuid), None
    )
    if not result or not result.result:
        abort(404)
    return Response(result.result, mimetype="text/xml", headers={"Content-Type": "text/xml"})


@app.route("/transform/success/<job_id>/original/<uuid>")
def transform_original(job_id: str, uuid: str):
    job = get_job(job_id)
    if not job or not job.result:
        abort(404)
    result: TransformBatchRecord | None = next(
        (j for j in job.result.records if j.uuid == uuid), None
    )
    if not result or not result.original:
        abort(404)
    return Response(result.original, mimetype="text/xml", headers={"Content-Type": "text/xml"})


@app.route("/transform/success/<job_id>/diff/<uuid>")
def transform_diff(job_id: str, uuid: str):
    job = get_job(job_id)
    if not job or not job.result:
        abort(404)
    result: SuccessTransformBatchRecord | None = next(
        (j for j in job.result.records if j.uuid == uuid), None
    )
    if not result or not result.original or not result.result:
        abort(404)
    diff = difflib.unified_diff(
        result.original.decode("utf-8").splitlines(),
        result.result.decode("utf-8").splitlines(),
        fromfile=result.uuid,
        tofile=result.uuid,
        lineterm="",
    )
    return render_template("diff.html.j2", diff="\n".join(diff))


@app.route("/transform/job_status/<job_id>")
def transform_job_status(job_id: str):
    url, _, _ = connection_infos()
    return render_template(
        "fragments/transform_job_status.html.j2",
        job=get_job(job_id),
        now=datetime.now().isoformat(timespec="seconds"),
        url=url,
        MigrateMode=MigrateMode,
        SkipReasonMessage=SkipReasonMessage,
    )


@app.route("/transform/results_preview/<job_id>")
def transform_results_preview(job_id: str):
    url, username, password = connection_infos()
    migrator = Migrator(url=url, username=username, password=password)
    job = get_job(job_id)
    if not job:
        abort(404)
    statuses = request.args.getlist("status", type=int)
    results = job.result.filter_status(statuses)
    return render_template(
        "fragments/transform_results_preview.html.j2",
        job=job,
        results=results,
        uuid_filter=migrator.gn.uuid_filter([r.uuid for r in results]),
        url=url,
    )


@app.route("/transform/download_result/<job_id>")
def transform_download_result(job_id: str):
    job = get_job(job_id)
    if not job:
        abort(404)
    return send_file(
        io.BytesIO(job.result.to_mef()),
        mimetype="application/zip",
        download_name=f"{job_id}.zip",
        as_attachment=True,
    )


@app.route("/migrate/<job_id>", methods=["POST"])
@authenticated()
def migrate(job_id: str):
    transform_job = get_job(job_id)
    if not transform_job:
        abort(404)
    url, username, password = connection_infos()
    mode = request.form.get("mode")
    mode = MigrateMode(mode)
    group = request.form.get("group")
    overwrite = mode == MigrateMode.OVERWRITE
    if not overwrite and not group:
        abort(400, "Missing `group` parameter")
    update_date_stamp = request.form.get("update_date_stamp") is not None
    statuses = request.form.getlist("status", type=int)
    migrator = Migrator(url=url, username=username, password=password)
    # TODO: filter by status here to avoid serializing records that won't be migrated
    migrate_job = get_queue().enqueue(
        migrator.migrate,
        transform_job.result,
        statuses=statuses,
        overwrite=overwrite,
        group=group,
        update_date_stamp=update_date_stamp,
        job_timeout=app.config["MIGRATE_TIMEOUT"],
        result_ttl=app.config["MIGRATE_TTL"],
        transform_job_id=job_id,
    )
    return redirect(url_for("migrate_success", job_id=migrate_job.id))


@app.route("/migrate/success/<job_id>")
def migrate_success(job_id: str):
    job = get_job(job_id)
    if not job:
        abort(404)
    return render_template("migrate.html.j2", job=job)


@app.route("/migrate/job_status/<job_id>")
@authenticated()
def migrate_job_status(job_id: str):
    url, _, _ = connection_infos()
    return render_template(
        "fragments/migrate_job_status.html.j2",
        job=get_job(job_id),
        now=datetime.now().isoformat(timespec="seconds"),
        url=url,
        MigrateMode=MigrateMode,
    )


@app.route("/migrate/update_mode")
@authenticated()
def migrate_update_mode():
    mode = request.args.get("mode")
    mode = MigrateMode(mode)
    groups = []
    if mode == MigrateMode.CREATE:
        url, username, password = connection_infos()
        migrator = Migrator(url=url, username=username, password=password)
        groups = migrator.gn.get_groups()
    return render_template(
        "fragments/migrate_update_mode.html.j2",
        migrate_mode=mode,
        groups=groups,
        MigrateMode=MigrateMode,
    )


@app.route("/migrate/results_preview/<job_id>")
def migrate_results_preview(job_id: str):
    url, username, password = connection_infos()
    migrator = Migrator(url=url, username=username, password=password)
    job = get_job(job_id)
    if not job:
        abort(404)
    statuses = request.args.getlist("status", type=int)
    results = job.result.filter_status(statuses)
    return render_template(
        "fragments/migrate_results_preview.html.j2",
        job=job,
        results=results,
        uuid_filter=migrator.gn.uuid_filter([r.target_uuid for r in results]),
        url=url,
        MigrateMode=MigrateMode,
    )


@app.route("/docs")
def documentation():
    index_page = Path("doc/index.md")
    if not index_page.exists():
        abort(404)
    index_content = index_page.read_text()
    tdocs_toc = "<ul>"
    for tdoc in sorted(app.config["TRANSFORMATIONS_PATH"].glob("*.md")):
        tdocs_toc += f'<li><a href="{url_for("documentation_transformation", transformation=tdoc.stem)}">{tdoc.stem}</a></li>'
    tdocs_toc += "</ul>"
    index_content = index_content.replace("<!-- insert:transformations_docs -->", tdocs_toc)
    return render_template(
        "documentation.html.j2",
        content=render_markdown(index_content),
    )


@app.route("/docs/transformations/<transformation>")
def documentation_transformation(transformation: str):
    doc_page = app.config["TRANSFORMATIONS_PATH"] / f"{transformation}.md"
    if not doc_page.exists():
        abort(404)
    md_content = doc_page.read_text()
    return render_template(
        "documentation.html.j2",
        content=render_markdown(md_content),
    )


if __name__ == "__main__":
    app.run(debug=True)
