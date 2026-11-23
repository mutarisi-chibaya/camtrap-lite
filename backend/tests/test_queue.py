from sqlalchemy.orm import Session, sessionmaker

from app.models import Job, JobStatus
from app.queue import DbQueue


def _queue(db: Session) -> DbQueue:
    return DbQueue(sessionmaker(bind=db.get_bind(), expire_on_commit=False))


def test_claim_order_and_empty(db: Session) -> None:
    q = _queue(db)
    first = q.enqueue("detect", {"image_ids": [1]})
    second = q.enqueue("detect", {"image_ids": [2]})

    job = q.claim()
    assert job is not None and job.id == first and job.attempts == 1
    job2 = q.claim()
    assert job2 is not None and job2.id == second
    assert q.claim() is None


def test_retry_then_fail_after_max_attempts(db: Session) -> None:
    q = _queue(db)
    job_id = q.enqueue("detect", {})
    for attempt in range(1, 4):
        job = q.claim()
        assert job is not None and job.attempts == attempt
        q.fail(job_id, f"boom {attempt}")

    row = db.get_one(Job, job_id)
    db.refresh(row)
    assert row.status == JobStatus.failed
    assert row.error == "boom 3"
    assert q.claim() is None


def test_complete(db: Session) -> None:
    q = _queue(db)
    job_id = q.enqueue("detect", {})
    q.claim()
    q.complete(job_id)
    row = db.get_one(Job, job_id)
    db.refresh(row)
    assert row.status == JobStatus.done
