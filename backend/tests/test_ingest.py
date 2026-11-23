from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Camera, Image, ImageStatus, Job, TimestampSource
from app.services.ingest import (
    InvalidImageError,
    read_image_info,
    timestamp_from_filename,
)
from app.storage import LocalStorage
from tests.helpers import make_jpeg


def test_exif_timestamp_wins_over_filename() -> None:
    data = make_jpeg((80, 60), taken=datetime(2017, 10, 4, 1, 1, 44))
    w, h, ts, src = read_image_info(data, "20200101_120000.jpg")
    assert (w, h) == (80, 60)
    assert ts == datetime(2017, 10, 4, 1, 1, 44)
    assert src == TimestampSource.exif


def test_filename_timestamp_fallback() -> None:
    _, _, ts, src = read_image_info(make_jpeg(), "CAM1_2021-03-05 14-22-09.jpg")
    assert ts == datetime(2021, 3, 5, 14, 22, 9)
    assert src == TimestampSource.filename


def test_missing_timestamp() -> None:
    _, _, ts, src = read_image_info(make_jpeg(), "IMAG0073.JPG")
    assert ts is None
    assert src == TimestampSource.missing


@pytest.mark.parametrize("name", ["20211305_120000.jpg", "18000101_000000.jpg", "IMG_1234.jpg"])
def test_filename_rejects_impossible_dates(name: str) -> None:
    assert timestamp_from_filename(name) is None


def test_invalid_image_raises() -> None:
    with pytest.raises(InvalidImageError):
        read_image_info(b"not an image", "x.jpg")


def test_local_storage_rejects_path_escape(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.exists("../outside.txt")


def test_upload_creates_images_and_batched_jobs(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.ingest.get_settings", lambda: _settings(batch_size=2))
    cam = client.post("/cameras", json={"name": "A01", "site_name": "Karoo"}).json()

    files = [("files", (f"img{i}.jpg", make_jpeg(), "image/jpeg")) for i in range(3)]
    files.append(("files", ("notes.txt", b"hello", "text/plain")))
    r = client.post(f"/cameras/{cam['id']}/images", files=files)

    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["images"]) == 3
    assert [x["filename"] for x in body["rejected"]] == ["notes.txt"]
    assert len(body["job_ids"]) == 2  # 3 images, batch size 2
    assert {i.status for i in db.query(Image)} == {ImageStatus.queued}
    payloads = [j.payload["image_ids"] for j in db.query(Job).order_by(Job.id)]
    assert [len(p) for p in payloads] == [2, 1]

    image_id = body["images"][0]["id"]
    f = client.get(f"/images/{image_id}/file")
    assert f.status_code == 200
    assert f.headers["content-type"] == "image/jpeg"
    assert f.content[:2] == b"\xff\xd8"

    cams = client.get("/cameras").json()
    assert cams[0]["image_count"] == 3


def test_upload_unknown_camera(client: TestClient) -> None:
    r = client.post("/cameras/999/images", files=[("files", ("a.jpg", make_jpeg(), "image/jpeg"))])
    assert r.status_code == 404


def test_api_key_required_when_configured(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.deps.get_settings", lambda: _settings(api_key="secret"))
    assert client.post("/cameras", json={"name": "x"}).status_code == 401
    ok = client.post("/cameras", json={"name": "x"}, headers={"X-API-Key": "secret"})
    assert ok.status_code == 201
    assert db.query(Camera).count() == 1


def _settings(**overrides: object):  # type: ignore[no-untyped-def]
    from app.config import Settings

    return Settings(**overrides)  # type: ignore[arg-type]
