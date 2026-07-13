from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./.data/ltx.db"
    storage_root: Path = Path("./.data/object-storage")
    bootstrap_api_key: str = "dev-api-key"
    admin_token: str = "dev-admin-token"
    public_base_url: str = "http://localhost:8000"
    require_env: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("LTX_DATABASE_URL", cls.database_url),
            storage_root=Path(os.getenv("LTX_STORAGE_ROOT", str(cls.storage_root))),
            bootstrap_api_key=os.getenv("LTX_BOOTSTRAP_API_KEY", cls.bootstrap_api_key),
            admin_token=os.getenv("LTX_ADMIN_TOKEN", cls.admin_token),
            public_base_url=os.getenv("LTX_PUBLIC_BASE_URL", cls.public_base_url),
            require_env=os.getenv("LTX_REQUIRE_ENV", "false").lower() in {"1", "true", "yes"},
        )

    def validate_required(self) -> None:
        if not self.require_env:
            return
        required = {
            "LTX_DATABASE_URL": self.database_url,
            "LTX_STORAGE_ROOT": str(self.storage_root),
            "LTX_BOOTSTRAP_API_KEY": self.bootstrap_api_key,
            "LTX_ADMIN_TOKEN": self.admin_token,
        }
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
