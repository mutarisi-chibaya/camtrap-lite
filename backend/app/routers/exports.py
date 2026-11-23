import json
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.db import DbSession
from app.services.export_coco import export_coco
from app.services.export_csv import export_csv

router = APIRouter(prefix="/exports", tags=["exports"])

MinConf = Annotated[float, Query(ge=0, le=1, description="minimum detection confidence")]


def _attachment(name: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


@router.get("/csv")
def get_csv(db: DbSession, camera_id: int | None = None, min_conf: MinConf = 0.2) -> Response:
    """One row per image: camera, site, time, event, final label (human over AI), detections."""
    return Response(
        export_csv(db, camera_id, min_conf),
        media_type="text/csv",
        headers=_attachment("camtrap_export.csv"),
    )


@router.get("/coco")
def get_coco(db: DbSession, camera_id: int | None = None, min_conf: MinConf = 0.2) -> Response:
    """COCO JSON with pixel bboxes [x, y, width, height]."""
    return Response(
        json.dumps(export_coco(db, camera_id, min_conf)),
        media_type="application/json",
        headers=_attachment("camtrap_export_coco.json"),
    )
