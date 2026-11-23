from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Job, JobStatus, JobType
from app.queue.base import JobQueue, QueuedJob

MAX_ATTEMPTS = 3


class DbQueue(JobQueue):
    """A queue backed by the `jobs` table.

    `claim` uses ``SELECT ... FOR UPDATE SKIP LOCKED`` on Postgres, so several workers
    can poll the same table without taking the same job. SQLite ignores the hint; it is
    only used for tests and single-worker local runs.
    """

    def __init__(self, session_factory: sessionmaker[Session], max_attempts: int = MAX_ATTEMPTS):
        self._sessions = session_factory
        self.max_attempts = max_attempts

    def enqueue(self, job_type: str, payload: dict[str, Any]) -> int:
        with self._sessions() as db:
            job = Job(type=JobType(job_type), payload=payload)
            db.add(job)
            db.commit()
            return job.id

    def claim(self) -> QueuedJob | None:
        with self._sessions() as db:
            stmt = (
                select(Job)
                .where(Job.status == JobStatus.pending)
                .order_by(Job.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = db.scalars(stmt).first()
            if job is None:
                return None
            job.status = JobStatus.running
            job.attempts += 1
            db.commit()
            return QueuedJob(job.id, job.type.value, dict(job.payload), job.attempts)

    def complete(self, job_id: int) -> None:
        with self._sessions() as db:
            job = db.get_one(Job, job_id)
            job.status = JobStatus.done
            job.error = None
            db.commit()

    def fail(self, job_id: int, error: str) -> None:
        with self._sessions() as db:
            job = db.get_one(Job, job_id)
            job.error = error[-2000:]
            job.status = (
                JobStatus.failed if job.attempts >= self.max_attempts else JobStatus.pending
            )
            db.commit()
