"""Storage interface.

The rest of the app only talks to `Storage`, never to the filesystem directly, so an
S3 implementation (keys -> object keys, `open_read` -> `get_object`) could be added
without touching routers, worker or services.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, data: BinaryIO) -> None:
        """Store a file under `key` (a relative, '/'-separated path)."""

    @abstractmethod
    def open_read(self, key: str) -> BinaryIO:
        """Open a stored file for reading. Raises FileNotFoundError if missing."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...
