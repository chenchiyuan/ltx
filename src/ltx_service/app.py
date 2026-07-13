from __future__ import annotations

from fastapi import FastAPI

from .api import build_router
from .bootstrap import seed_defaults
from .config import Settings
from .database import create_session_factory
from .dependencies import AppState, make_get_session
from .executor import MockLocalExecutor
from .storage import build_storage_adapter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate_required()
    session_factory = create_session_factory(settings)
    with session_factory() as session:
        seed_defaults(session, settings.bootstrap_api_key)

    storage = build_storage_adapter(settings)
    executor = MockLocalExecutor()
    state = AppState(
        session_factory=session_factory,
        storage=storage,
        admin_token=settings.admin_token,
        worker_token=settings.worker_token,
        public_base_url=settings.public_base_url,
    )

    app = FastAPI(title="LTX Video Service", version="0.1.0")
    app.include_router(build_router(state, make_get_session(session_factory), executor))
    app.state.ltx = state
    return app


app = create_app()
