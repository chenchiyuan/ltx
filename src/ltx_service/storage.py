from __future__ import annotations

from pathlib import Path


class ObjectStorageAdapter:
    def write_bytes(self, uri: str, data: bytes) -> int:
        raise NotImplementedError

    def read_bytes(self, uri: str) -> bytes:
        raise NotImplementedError

    def exists(self, uri: str) -> bool:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError


class LocalObjectStorage(ObjectStorageAdapter):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, uri: str) -> Path:
        if not uri.startswith("local://"):
            raise ValueError(f"Unsupported storage URI: {uri}")
        relative = uri.removeprefix("local://").lstrip("/")
        path = (self.root / relative).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError("Storage URI escapes storage root")
        return path

    def write_bytes(self, uri: str, data: bytes) -> int:
        path = self._path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    def read_bytes(self, uri: str) -> bytes:
        return self._path(uri).read_bytes()

    def exists(self, uri: str) -> bool:
        return self._path(uri).exists()

    def health(self) -> dict:
        return {"type": "local", "healthy": self.root.exists()}
