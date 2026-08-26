"""
File storage abstraction. `STORAGE_BACKEND=local` for dev/tests (writes to
disk under LOCAL_STORAGE_DIR), `STORAGE_BACKEND=azure_blob` for the deployed
version — matches the Azure App Service target without any pipeline code
caring which one is active. DocumentService depends on `FileStorage`, never
on a specific backend.
"""
import hashlib
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import Settings, get_settings


class FileStorage(ABC):
    @abstractmethod
    def save(self, content: bytes, original_filename: str) -> str:
        """Persists `content` and returns a backend-specific path/URL that
        can be handed back to `read` later.
        """
        raise NotImplementedError

    @abstractmethod
    def read(self, path: str) -> bytes:
        raise NotImplementedError


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class LocalFileStorage(FileStorage):
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, original_filename: str) -> str:
        suffix = Path(original_filename).suffix
        # Random name, not the original filename: avoids path traversal from
        # a hostile filename ("../../etc/passwd.pdf") and collisions between
        # two uploads that happen to share a name.
        stored_name = f"{uuid.uuid4()}{suffix}"
        dest = self.base_dir / stored_name
        dest.write_bytes(content)
        return str(dest)

    def read(self, path: str) -> bytes:
        return Path(path).read_bytes()


class AzureBlobFileStorage(FileStorage):
    def __init__(self, connection_string: str, container: str):
        from azure.storage.blob import BlobServiceClient

        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container
        self._container = self._service.get_container_client(container)
        try:
            self._container.create_container()
        except Exception:
            pass  # already exists — fine, this runs once at startup

    def save(self, content: bytes, original_filename: str) -> str:
        suffix = Path(original_filename).suffix
        blob_name = f"{uuid.uuid4()}{suffix}"
        self._container.upload_blob(blob_name, content)
        return f"azure://{self._container_name}/{blob_name}"

    def read(self, path: str) -> bytes:
        blob_name = path.split("/")[-1]
        return self._container.download_blob(blob_name).readall()


def get_file_storage(settings: Settings | None = None) -> FileStorage:
    settings = settings or get_settings()
    if settings.storage_backend == "azure_blob":
        if not settings.azure_storage_connection_string:
            raise RuntimeError("STORAGE_BACKEND=azure_blob requires AZURE_STORAGE_CONNECTION_STRING")
        return AzureBlobFileStorage(settings.azure_storage_connection_string, settings.azure_storage_container)
    return LocalFileStorage(settings.local_storage_dir)
