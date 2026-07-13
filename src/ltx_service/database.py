from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import Base


def create_engine_for_settings(settings: Settings):
    if settings.database_url.startswith("sqlite:///") and settings.database_url != "sqlite:///:memory:":
        database_path = settings.database_url.removeprefix("sqlite:///")
        if database_path:
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine_for_settings(settings)
    Base.metadata.create_all(engine)
    ensure_compatible_schema(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def ensure_compatible_schema(engine) -> None:
    inspector = inspect(engine)
    if "task_attempts" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("task_attempts")}
    if "worker_id" in existing_columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE task_attempts ADD COLUMN worker_id VARCHAR"))


def session_dependency(factory: sessionmaker[Session]):
    def get_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    return get_session
