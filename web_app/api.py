"""JSON API for the asset database.

Endpoints
---------
GET    /api/assets                 list / search assets
GET    /api/assets/<id>            single asset
POST   /api/assets                 create asset
PUT    /api/assets/<id>            modify asset
PATCH  /api/assets/<id>            modify asset
DELETE /api/assets/<id>            delete asset

Searching (GET /api/assets):
  * filter by any of: id, name, author, version, status
      /api/assets?name=monkey
  * limit the returned keys with fields:
      /api/assets?name=monkey&fields=id,status,steps
  * status_stable flag: instead of the matched record itself, return the
    version of the same asset (same name) that is marked "stable":
      /api/assets?name=monkey&version=v002&status_stable=1

Creating / modifying:
  * JSON body with keys: name, author, version, status, modified_by and
    steps ({"model": 3} or {"model": {"value": 3, "status": "stable"}},
    null value removes the step on modify).
  * an image can be sent either as a multipart file field "preview_img"
    (the other fields go in the form, steps as a JSON string) or inside
    the JSON body as base64 in "preview_img_b64" (+ "preview_img_name").
    It is saved into database/preview_img and linked to the record.
"""

import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from flask import Blueprint, jsonify, request

from database import get_session, manager
from database.manager import ValidationError

api_bp = Blueprint("api", __name__, url_prefix="/api")

TRUE_VALUES = {"1", "true", "yes", "on"}


@api_bp.errorhandler(ValidationError)
def _bad_request(exc):
    return jsonify({"error": str(exc)}), 400


def _parse_fields():
    raw = request.args.get("fields")
    if not raw:
        return None
    return [field.strip() for field in raw.split(",") if field.strip()]


def _flag(name):
    return request.args.get(name, "").lower() in TRUE_VALUES


def _serialize(session, asset, fields, status_stable):
    """Serialize an asset; with status_stable resolve to the stable version."""
    if status_stable:
        stable = manager.get_stable_version(session, asset)
        if stable is None:
            return {
                "requested_id": asset.id,
                "name": asset.name,
                "stable_version": None,
                "note": f"asset '{asset.name}' has no version marked stable",
            }
        asset = stable
    return manager.asset_to_dict(asset, fields)


def _extract_payload():
    """Read the record data + optional image from a JSON or multipart request.

    Returns (data, image, image_name) where image is bytes / file object.
    """
    if request.content_type and "multipart/form-data" in request.content_type:
        data = {key: value for key, value in request.form.items()}
        if "steps" in data and isinstance(data["steps"], str) and data["steps"].strip():
            try:
                data["steps"] = json.loads(data["steps"])
            except json.JSONDecodeError:
                raise ValidationError("Form field 'steps' must be valid JSON")
        elif "steps" in data:
            data.pop("steps")
        upload = request.files.get("preview_img")
        if upload and upload.filename:
            return data, upload, upload.filename
        return data, None, None

    data = request.get_json(silent=True)
    if data is None:
        raise ValidationError("Request body must be JSON or multipart/form-data")
    image = None
    image_name = data.pop("preview_img_name", None)
    b64 = data.pop("preview_img_b64", None)
    if b64:
        image = manager.decode_base64_image(b64)
    return data, image, image_name


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@api_bp.route("/assets", methods=["GET"])
def list_assets():
    filters = {
        key: request.args.get(key)
        for key in ("id", "name", "author", "version", "status")
        if request.args.get(key) not in (None, "")
    }
    fields = _parse_fields()
    status_stable = _flag("status_stable")

    with get_session() as session:
        assets = manager.find_assets(session, filters)
        if status_stable:
            # several versions of one asset resolve to the same stable record
            unique, seen = [], set()
            for asset in assets:
                if asset.name not in seen:
                    seen.add(asset.name)
                    unique.append(asset)
            assets = unique
        results = [_serialize(session, asset, fields, status_stable) for asset in assets]
    return jsonify({"count": len(results), "assets": results})


@api_bp.route("/assets/<int:asset_id>", methods=["GET"])
def get_asset(asset_id):
    with get_session() as session:
        asset = manager.get_asset(session, asset_id)
        if not asset:
            return jsonify({"error": f"Asset {asset_id} not found"}), 404
        entry = _serialize(session, asset, _parse_fields(), _flag("status_stable"))
    return jsonify(entry)


@api_bp.route("/assets", methods=["POST"])
def create_asset():
    data, image, image_name = _extract_payload()
    with get_session() as session:
        asset = manager.create_asset(session, data, image=image, image_name=image_name)
        session.flush()
        entry = manager.asset_to_dict(asset)
    return jsonify(entry), 201


@api_bp.route("/assets/<int:asset_id>", methods=["PUT", "PATCH"])
def modify_asset(asset_id):
    data, image, image_name = _extract_payload()
    with get_session() as session:
        asset = manager.get_asset(session, asset_id)
        if not asset:
            return jsonify({"error": f"Asset {asset_id} not found"}), 404
        manager.update_asset(session, asset, data, image=image, image_name=image_name)
        session.flush()
        entry = manager.asset_to_dict(asset)
    return jsonify(entry)


@api_bp.route("/assets/<int:asset_id>", methods=["DELETE"])
def delete_asset(asset_id):
    with get_session() as session:
        asset = manager.get_asset(session, asset_id)
        if not asset:
            return jsonify({"error": f"Asset {asset_id} not found"}), 404
        manager.delete_asset(session, asset)
    return jsonify({"deleted": asset_id})
