"""Studio asset database web app.

Run from the project root:  python3 web_app/app.py
Web UI:  http://127.0.0.1:5000/
API:     http://127.0.0.1:5000/api/assets
"""

import os
import sys

# make the project root importable so "database" resolves
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for

from database import PREVIEW_IMG_DIR, STATUSES, init_db, get_session, manager
from database.manager import ValidationError

from api import api_bp

app = Flask(__name__)
app.secret_key = "monke-pipeline-dev-key"  # only used for flash messages
app.register_blueprint(api_bp)

init_db()


# ---------------------------------------------------------------------------
# web pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    filters = {
        key: request.args.get(key)
        for key in ("name", "author", "status")
        if request.args.get(key)
    }
    with get_session() as session:
        assets = manager.find_assets(session, filters)
        rows = [manager.asset_to_dict(asset) for asset in assets]
    return render_template("index.html", assets=rows, statuses=STATUSES, filters=filters)


@app.route("/assets/add", methods=["GET", "POST"])
def add_asset():
    if request.method == "POST":
        return _handle_form(asset_id=None)
    return render_template("asset_form.html", asset=None, statuses=STATUSES)


@app.route("/assets/<int:asset_id>/edit", methods=["GET", "POST"])
def edit_asset(asset_id):
    if request.method == "POST":
        return _handle_form(asset_id=asset_id)
    with get_session() as session:
        asset = manager.get_asset(session, asset_id)
        if not asset:
            flash(f"Asset {asset_id} not found", "error")
            return redirect(url_for("index"))
        data = manager.asset_to_dict(asset)
    return render_template("asset_form.html", asset=data, statuses=STATUSES)


@app.route("/assets/<int:asset_id>/delete", methods=["POST"])
def delete_asset(asset_id):
    with get_session() as session:
        asset = manager.get_asset(session, asset_id)
        if asset:
            manager.delete_asset(session, asset)
            flash(f"Asset {asset_id} deleted", "ok")
    return redirect(url_for("index"))


def _handle_form(asset_id):
    """Shared handler for the add / edit forms."""
    form = request.form
    data = {
        "name": form.get("name"),
        "author": form.get("author"),
        "version": form.get("version"),
        "status": form.get("status"),
        "modified_by": form.get("modified_by"),
        "steps": _steps_from_form(form),
    }
    image = request.files.get("preview_img")
    image = image if image and image.filename else None

    try:
        with get_session() as session:
            if asset_id is None:
                asset = manager.create_asset(session, data, image=image)
                flash(f"Asset '{asset.name}' created (id {asset.id})", "ok")
            else:
                asset = manager.get_asset(session, asset_id)
                if not asset:
                    flash(f"Asset {asset_id} not found", "error")
                    return redirect(url_for("index"))
                manager.update_asset(session, asset, data, image=image)
                flash(f"Asset '{asset.name}' updated", "ok")
    except ValidationError as exc:
        flash(str(exc), "error")
        target = url_for("add_asset") if asset_id is None else url_for("edit_asset", asset_id=asset_id)
        return redirect(target)
    return redirect(url_for("index"))


def _steps_from_form(form):
    """Build the steps dict from the dynamic form rows.

    The submitted rows are the complete set: existing keys that are not
    submitted any more get removed (value None).
    """
    steps = {}
    keys = form.getlist("step_key")
    values = form.getlist("step_value")
    statuses = form.getlist("step_status")
    for key, value, status in zip(keys, values, statuses):
        key = key.strip()
        if key:
            steps[key] = {"value": value, "status": status}
    for old_key in form.get("existing_step_keys", "").split(","):
        old_key = old_key.strip()
        if old_key and old_key not in steps:
            steps[old_key] = None  # removed in the form
    return steps


# ---------------------------------------------------------------------------
# preview images
# ---------------------------------------------------------------------------

@app.route("/preview_img/<path:filename>")
def preview_img(filename):
    return send_from_directory(PREVIEW_IMG_DIR, filename)


if __name__ == "__main__":
    app.run(debug=True)
