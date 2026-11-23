from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Camera, Detection, DetectionCategory, Image, Job, JobStatus, JobType

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_docs_load(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_models_round_trip(db: Session) -> None:
    cam = Camera(name="cam-01", site_name="Karoo A")
    img = Image(camera=cam, original_filename="a.jpg", storage_key="1/a.jpg")
    img.detections.append(
        Detection(
            category=DetectionCategory.animal,
            confidence=0.91,
            bbox_x=0.1,
            bbox_y=0.2,
            bbox_w=0.3,
            bbox_h=0.4,
        )
    )
    db.add_all([cam, Job(type=JobType.detect, payload={"image_ids": [1]})])
    db.commit()

    stored = db.get(Image, img.id)
    assert stored is not None
    assert stored.status == "uploaded"
    assert stored.timestamp_source == "missing"
    assert stored.detections[0].category == DetectionCategory.animal
    job = db.query(Job).one()
    assert job.status == JobStatus.pending
    assert job.payload == {"image_ids": [1]}


def test_alembic_migration_matches_models(tmp_path: Path) -> None:
    """The migration must create every table and column the models declare."""
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    insp = inspect(create_engine(url))
    for table in Base.metadata.sorted_tables:
        migrated = {c["name"] for c in insp.get_columns(table.name)}
        assert migrated == {c.name for c in table.columns}, table.name
