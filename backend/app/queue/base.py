"""Job queue interface.

`DbQueue` is the only implementation. An SQS version would map `enqueue` to
`send_message`, `claim` to `receive_message` (visibility timeout = lease) and
`complete` to `delete_message`; callers would not change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueuedJob:
    id: int
    type: str
    payload: dict[str, Any]
    attempts: int


class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, job_type: str, payload: dict[str, Any]) -> int:
        """Add a job and return its id."""

    @abstractmethod
    def claim(self) -> QueuedJob | None:
        """Atomically take the oldest pending job, or None if the queue is empty."""

    @abstractmethod
    def complete(self, job_id: int) -> None: ...

    @abstractmethod
    def fail(self, job_id: int, error: str) -> None:
        """Record a failure: requeue if attempts remain, else mark the job failed."""
