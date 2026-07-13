from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from .config import Settings


def _safe_uri_path(*parts: str) -> str:
    cleaned: list[str] = []
    for part in parts:
        value = str(part).replace("\\", "/")
        for piece in value.split("/"):
            if not piece or piece == ".":
                continue
            if piece == "..":
                raise ValueError("Storage URI component cannot traverse parent directories")
            cleaned.append(piece)
    if not cleaned:
        raise ValueError("Storage URI requires at least one path component")
    return "/".join(cleaned)


class ObjectStorageAdapter:
    def uri_for(self, *parts: str) -> str:
        raise NotImplementedError

    def write_bytes(self, uri: str, data: bytes) -> int:
        raise NotImplementedError

    def read_bytes(self, uri: str) -> bytes:
        raise NotImplementedError

    def exists(self, uri: str) -> bool:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError


class LocalSharedObjectStorage(ObjectStorageAdapter):
    def __init__(self, root: Path):
        self.root = root

    def uri_for(self, *parts: str) -> str:
        return f"local://{_safe_uri_path(*parts)}"

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
        probe = self.root / f".health-{uuid4().hex}"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b"ok")
            healthy = probe.read_bytes() == b"ok"
            return {"type": "local_shared", "healthy": healthy}
        except OSError as exc:
            return {"type": "local_shared", "healthy": False, "reason": exc.__class__.__name__}
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass


class MinioObjectStorage(ObjectStorageAdapter):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.secure = secure
        self._client = None

    def uri_for(self, *parts: str) -> str:
        return f"minio://{self.bucket}/{_safe_uri_path(*parts)}"

    def _object_name(self, uri: str) -> str:
        prefix = f"minio://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(f"Unsupported storage URI: {uri}")
        object_name = uri.removeprefix(prefix)
        if not object_name or ".." in object_name.split("/"):
            raise ValueError("Storage URI component cannot traverse parent directories")
        return object_name

    def _get_client(self):
        if self._client is None:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError("MinIO storage backend requires the optional 'minio' package") from exc
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    def write_bytes(self, uri: str, data: bytes) -> int:
        self._get_client().put_object(self.bucket, self._object_name(uri), BytesIO(data), len(data))
        return len(data)

    def read_bytes(self, uri: str) -> bytes:
        response = self._get_client().get_object(self.bucket, self._object_name(uri))
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, uri: str) -> bool:
        try:
            self._get_client().stat_object(self.bucket, self._object_name(uri))
        except Exception:
            return False
        return True

    def health(self) -> dict:
        try:
            healthy = self._get_client().bucket_exists(self.bucket)
        except Exception as exc:
            return {"type": "minio", "healthy": False, "reason": exc.__class__.__name__}
        return {"type": "minio", "healthy": bool(healthy)}


LocalObjectStorage = LocalSharedObjectStorage


def build_storage_adapter(settings: Settings) -> ObjectStorageAdapter:
    if settings.storage_backend == "local_shared":
        return LocalSharedObjectStorage(settings.storage_root)
    if settings.storage_backend == "minio":
        missing = [
            name
            for name, value in {
                "LTX_MINIO_ENDPOINT": settings.minio_endpoint,
                "LTX_MINIO_ACCESS_KEY": settings.minio_access_key,
                "LTX_MINIO_SECRET_KEY": settings.minio_secret_key,
                "LTX_MINIO_BUCKET": settings.minio_bucket,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required MinIO settings: {', '.join(missing)}")
        return MinioObjectStorage(
            settings.minio_endpoint or "",
            settings.minio_access_key or "",
            settings.minio_secret_key or "",
            settings.minio_bucket or "",
            settings.minio_secure,
        )
    raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
