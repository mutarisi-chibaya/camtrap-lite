"""Shared fixtures: an in-memory SQLite database and a FastAPI test client."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base, get_db
from app.deps import get_queue
from app.main import app
from app.queue import DbQueue
from app.storage import LocalStorage, get_storage


@pytest.fixture
def db() -> Iterator[Session]:
    # StaticPool: one shared connection, so every session sees the same :memory: DB.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db: Session, tmp_path: Path) -> Iterator[TestClient]:
    storage = LocalStorage(tmp_path / "storage")
    queue = DbQueue(sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
