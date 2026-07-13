from __future__ import annotations

from pathlib import Path


class LocalSharedStorage:
    def __init__(self, root: Path):
        self.root = root

    def path_for_uri(self, uri: str) -> Path:
        if not uri.startswith("local://"):
            raise ValueError(f"Unsupported storage URI: {uri}")
        relative = uri.removeprefix("local://").lstrip("/")
        path = (self.root / relative).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError("Storage URI escapes storage root")
        return path

    def read_bytes(self, uri: str) -> bytes:
        return self.path_for_uri(uri).read_bytes()

    def write_bytes(self, uri: str, data: bytes) -> int:
        path = self.path_for_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)
