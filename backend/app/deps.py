"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import get_settings
from app.db import SessionLocal
from app.queue import DbQueue, JobQueue
from app.storage import Storage, get_storage


def get_queue() -> JobQueue:
    return DbQueue(SessionLocal)


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Single shared API key for write endpoints. Disabled when API_KEY is unset."""
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


StorageDep = Annotated[Storage, Depends(get_storage)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
WriteAuth = Depends(require_api_key)
