from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from .errors import api_error
from .ids import new_id
from .models import ApiKey, Asset
from .storage import ObjectStorageAdapter

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def ensure_upload_size(size_bytes: int) -> None:
    if size_bytes > MAX_UPLOAD_BYTES:
        raise api_error(413, "UPLOAD_TOO_LARGE", "Image must be 32 MB or smaller")


def create_upload_asset(
    session: Session,
    storage: ObjectStorageAdapter,
    api_key: ApiKey,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> Asset:
    ensure_upload_size(size_bytes)
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise api_error(422, "REQUEST_INVALID_PARAMETER", f"Unsupported content_type: {content_type}")
    asset_id = new_id("ast")
    asset = Asset(
        id=asset_id,
        api_key_id=api_key.id,
        kind="input",
        storage_uri=storage.uri_for("inputs", asset_id, filename),
        content_type=content_type,
        size_bytes=size_bytes,
        status="pending",
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def upload_asset_content(session: Session, storage: ObjectStorageAdapter, api_key: ApiKey, asset_id: str, data: bytes) -> Asset:
    ensure_upload_size(len(data))
    asset = get_owned_asset(session, api_key, asset_id)
    if asset.kind != "input":
        raise api_error(422, "REQUEST_INVALID_PARAMETER", "Only input assets can be uploaded by API clients")
    size = storage.write_bytes(asset.storage_uri, data)
    asset.size_bytes = size
    asset.status = "uploaded"
    session.commit()
    session.refresh(asset)
    return asset


def get_owned_asset(session: Session, api_key: ApiKey, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset or asset.api_key_id != api_key.id:
        raise api_error(404, "ASSET_NOT_FOUND", "Asset not found")
    return asset


def expires_at(minutes: int = 60) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
