from app.config import get_settings
from app.storage.base import Storage
from app.storage.local import LocalStorage


def get_storage() -> Storage:
    """The configured storage backend. Only LocalStorage exists; S3 would slot in here."""
    return LocalStorage(get_settings().storage_dir)


__all__ = ["Storage", "LocalStorage", "get_storage"]
