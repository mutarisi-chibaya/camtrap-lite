"""Re-run the static finder and triage for every camera (e.g. after changing thresholds).

    docker compose restart api        # so the API picks up the new .env values
    docker compose exec api python scripts/retriage.py

Human reviews and static-cluster decisions are kept; only automatic outcomes change.
"""

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Camera
from app.services.pipeline import post_process_camera


def main() -> None:
    s = get_settings()
    print(
        f"thresholds: auto-accept >= {s.auto_accept_conf}, auto-empty < {s.auto_empty_conf}, "
        f"static IoU {s.static_iou}, share {s.static_min_fraction}, count {s.static_min_count}"
    )
    with SessionLocal() as db:
        for camera_id, name in db.execute(select(Camera.id, Camera.name)).all():
            post_process_camera(db, camera_id)
            print(f"re-triaged camera {camera_id} ({name})")


if __name__ == "__main__":
    main()
