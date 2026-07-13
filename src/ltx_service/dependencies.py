from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .errors import api_error
from .models import ApiKey
from .security import hash_api_key
from .storage import ObjectStorageAdapter


@dataclass(frozen=True)
class AppState:
    session_factory: sessionmaker[Session]
    storage: ObjectStorageAdapter
    admin_token: str
    public_base_url: str


def make_get_session(factory: sessionmaker[Session]):
    def get_session():
        with factory() as session:
            yield session

    return get_session


def require_api_key(get_session):
    def dependency(
        authorization: str | None = Header(default=None, alias="Authorization"),
        session: Session = Depends(get_session),
    ) -> ApiKey:
        if not authorization or not authorization.startswith("Bearer "):
            raise api_error(401, "AUTH_INVALID_API_KEY", "Missing or invalid Authorization header")
        raw_key = authorization.removeprefix("Bearer ").strip()
        key = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key)))
        if not key:
            raise api_error(401, "AUTH_INVALID_API_KEY", "API key is invalid")
        if key.status != "active":
            raise api_error(403, "AUTH_KEY_DISABLED", "API key is disabled")
        return key

    return dependency


def require_admin_token(admin_token: str):
    def dependency(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
        if not x_admin_token:
            raise api_error(401, "ADMIN_TOKEN_REQUIRED", "Missing admin token")
        if x_admin_token != admin_token:
            raise api_error(403, "ADMIN_FORBIDDEN", "Invalid admin token")

    return dependency
