from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./.data/ltx.db"
    storage_backend: str = "local_shared"
    storage_root: Path = Path("./.data/object-storage")
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_secure: bool = False
    bootstrap_api_key: str = "dev-api-key"
    admin_token: str = "dev-admin-token"
    public_base_url: str = "http://localhost:8000"
    require_env: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("LTX_DATABASE_URL", cls.database_url),
            storage_backend=os.getenv("LTX_STORAGE_BACKEND", cls.storage_backend),
            storage_root=Path(os.getenv("LTX_STORAGE_ROOT", str(cls.storage_root))),
            minio_endpoint=os.getenv("LTX_MINIO_ENDPOINT"),
            minio_access_key=os.getenv("LTX_MINIO_ACCESS_KEY"),
            minio_secret_key=os.getenv("LTX_MINIO_SECRET_KEY"),
            minio_bucket=os.getenv("LTX_MINIO_BUCKET"),
            minio_secure=os.getenv("LTX_MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
            bootstrap_api_key=os.getenv("LTX_BOOTSTRAP_API_KEY", cls.bootstrap_api_key),
            admin_token=os.getenv("LTX_ADMIN_TOKEN", cls.admin_token),
            public_base_url=os.getenv("LTX_PUBLIC_BASE_URL", cls.public_base_url),
            require_env=os.getenv("LTX_REQUIRE_ENV", "false").lower() in {"1", "true", "yes"},
        )

    def validate_required(self) -> None:
        if not self.require_env:
            return
        if self.storage_backend not in {"local_shared", "minio"}:
            raise RuntimeError(f"Unsupported LTX_STORAGE_BACKEND: {self.storage_backend}")
        required = {
            "LTX_DATABASE_URL": self.database_url,
            "LTX_STORAGE_BACKEND": self.storage_backend,
            "LTX_BOOTSTRAP_API_KEY": self.bootstrap_api_key,
            "LTX_ADMIN_TOKEN": self.admin_token,
        }
        if self.storage_backend == "local_shared":
            required["LTX_STORAGE_ROOT"] = str(self.storage_root)
        elif self.storage_backend == "minio":
            required.update(
                {
                    "LTX_MINIO_ENDPOINT": self.minio_endpoint,
                    "LTX_MINIO_ACCESS_KEY": self.minio_access_key,
                    "LTX_MINIO_SECRET_KEY": self.minio_secret_key,
                    "LTX_MINIO_BUCKET": self.minio_bucket,
                }
            )
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
