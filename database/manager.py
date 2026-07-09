"""High level operations on the database, shared by the web app and the API.

Business rules implemented here:
  * status may only be one of STATUSES,
  * among all versions of the same asset (records sharing the same name)
    only one may be "stable" - publishing a new stable version demotes the
    previous stable one to "wip",
  * preview images are stored in database/preview_img and the Asset record
    only keeps the file name,
  * every step entry tracks its own status, modification date and the user
    who modified it.
"""

import base64
import os
import uuid

from sqlalchemy import select

from database.db import PREVIEW_IMG_DIR
from database.models import Asset, Step, STATUSES, STATUS_STABLE, STATUS_WIP, utcnow

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".exr"}


class ValidationError(ValueError):
    """Raised for bad user input; the API maps it to a 400 response."""


# ---------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------

def get_asset(session, asset_id):
    return session.get(Asset, asset_id)


def find_assets(session, filters=None):
    """Return assets matching the given field filters (exact match).

    Supported filter keys: id, name, author, version, status.
    """
    query = select(Asset)
    filters = filters or {}
    for field in ("id", "name", "author", "version", "status"):
        if field in filters and filters[field] not in (None, ""):
            query = query.where(getattr(Asset, field) == filters[field])
    return list(session.scalars(query.order_by(Asset.name, Asset.id)))


def get_stable_version(session, asset):
    """Return the record of the same asset (same name) marked as stable."""
    query = select(Asset).where(Asset.name == asset.name, Asset.status == STATUS_STABLE)
    return session.scalars(query).first()


# ---------------------------------------------------------------------------
# create / update
# ---------------------------------------------------------------------------

def create_asset(session, data, image=None, image_name=None):
    """Create a new asset record.

    data: dict with name (required), author, version, status and optionally
          steps (see _apply_steps for the accepted shapes).
    image / image_name: optional binary image content and its file name.
    """
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("Field 'name' is required")

    asset = Asset(
        name=name,
        author=(data.get("author") or "unknown").strip() or "unknown",
        version=(data.get("version") or "v001").strip() or "v001",
        status=_validate_status(data.get("status") or STATUS_WIP),
    )
    session.add(asset)
    session.flush()  # asset.id is needed for the image file name

    if data.get("steps"):
        _apply_steps(asset, data["steps"], data.get("modified_by"))
    if image:
        asset.preview_img = save_preview_image(image, asset.id, image_name)

    _ensure_single_stable(session, asset)
    return asset


def update_asset(session, asset, data, image=None, image_name=None):
    """Update an existing asset record. Only the provided keys change."""
    for field in ("name", "author", "version"):
        if field in data and data[field] not in (None, ""):
            setattr(asset, field, str(data[field]).strip())
    if data.get("status"):
        asset.status = _validate_status(data["status"])

    if "steps" in data and data["steps"] is not None:
        _apply_steps(asset, data["steps"], data.get("modified_by"))
    if image:
        _delete_preview_image(asset.preview_img)
        asset.preview_img = save_preview_image(image, asset.id, image_name)

    _ensure_single_stable(session, asset)
    return asset


def delete_asset(session, asset):
    _delete_preview_image(asset.preview_img)
    session.delete(asset)


def _validate_status(status):
    status = str(status).strip().lower()
    if status not in STATUSES:
        raise ValidationError(f"Invalid status {status!r}, must be one of {list(STATUSES)}")
    return status


def _ensure_single_stable(session, asset):
    """Demote other stable versions of the same asset name to wip."""
    if asset.status != STATUS_STABLE:
        return
    others = session.scalars(
        select(Asset).where(
            Asset.name == asset.name,
            Asset.status == STATUS_STABLE,
            Asset.id != asset.id,
        )
    )
    for other in others:
        other.status = STATUS_WIP


def _apply_steps(asset, steps, modified_by=None):
    """Merge step entries into the asset.

    Accepted shapes (dict keyed by step name):
      {"model": 3}                                    -- plain int value
      {"model": {"value": 3, "status": "stable"}}     -- with details
      {"model": null}                                 -- remove the entry
    """
    if not isinstance(steps, dict):
        raise ValidationError("'steps' must be a dict of {key: int} or {key: {...}}")
    modified_by = (modified_by or "unknown").strip() or "unknown"
    existing = {step.key: step for step in asset.steps}

    for key, raw in steps.items():
        key = str(key).strip()
        if not key:
            raise ValidationError("Step keys must be non empty strings")

        if raw is None:  # remove entry
            if key in existing:
                asset.steps.remove(existing[key])
            continue

        if isinstance(raw, dict):
            value = raw.get("value", existing[key].value if key in existing else 0)
            status = raw.get("status")
            user = raw.get("modified_by") or modified_by
        else:
            value, status, user = raw, None, modified_by

        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"Step {key!r} value must be an integer, got {value!r}")

        if key in existing:
            step = existing[key]
            step.value = value
            if status:
                step.status = _validate_status(status)
            step.modified_by = user
            step.modified_date = utcnow()
        else:
            asset.steps.append(
                Step(
                    key=key,
                    value=value,
                    status=_validate_status(status or STATUS_WIP),
                    modified_by=user,
                )
            )


# ---------------------------------------------------------------------------
# preview images
# ---------------------------------------------------------------------------

def save_preview_image(image, asset_id, original_name=None):
    """Save image bytes (or a file-like object) into the preview_img folder
    and return the stored file name."""
    if hasattr(image, "read"):
        content = image.read()
        original_name = original_name or getattr(image, "filename", None)
    else:
        content = image
    if not content:
        raise ValidationError("Empty image data")

    ext = os.path.splitext(original_name or "")[1].lower() or ".png"
    if ext not in ALLOWED_IMG_EXT:
        raise ValidationError(f"Unsupported image extension {ext!r}")

    filename = f"asset_{asset_id}_{uuid.uuid4().hex[:8]}{ext}"
    os.makedirs(PREVIEW_IMG_DIR, exist_ok=True)
    with open(os.path.join(PREVIEW_IMG_DIR, filename), "wb") as handle:
        handle.write(content)
    return filename


def decode_base64_image(data):
    """Decode an image sent through the JSON API as base64 text."""
    try:
        return base64.b64decode(data)
    except Exception:
        raise ValidationError("Field 'preview_img_b64' is not valid base64 data")


def _delete_preview_image(filename):
    if not filename:
        return
    path = os.path.join(PREVIEW_IMG_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

def asset_to_dict(asset, fields=None):
    """Serialize an Asset (and its steps) to a plain dict.

    fields: optional iterable limiting which keys are returned.
    """
    data = {
        "id": asset.id,
        "name": asset.name,
        "author": asset.author,
        "version": asset.version,
        "status": asset.status,
        "preview_img": f"/preview_img/{asset.preview_img}" if asset.preview_img else None,
        "created_date": asset.created_date.isoformat() if asset.created_date else None,
        "steps": {step.key: step.value for step in asset.steps},
        "steps_detail": {
            step.key: {
                "value": step.value,
                "status": step.status,
                "modified_date": step.modified_date.isoformat() if step.modified_date else None,
                "modified_by": step.modified_by,
            }
            for step in asset.steps
        },
    }
    if fields:
        unknown = set(fields) - set(data)
        if unknown:
            raise ValidationError(f"Unknown fields requested: {sorted(unknown)}")
        data = {key: data[key] for key in fields}
    return data
