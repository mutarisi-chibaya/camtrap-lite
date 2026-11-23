import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.db import DbSession
from app.deps import StorageDep
from app.models import Image

router = APIRouter(prefix="/images", tags=["images"])


@router.get("/{image_id}/file")
def get_image_file(image_id: int, db: DbSession, storage: StorageDep) -> StreamingResponse:
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")
    try:
        fh = storage.open_read(image.storage_key)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="image file missing from storage") from e
    media_type = mimetypes.guess_type(image.storage_key)[0] or "application/octet-stream"
    # Image files never change once stored, so the browser can cache them for the review UI.
    headers = {"Cache-Control": "public, max-age=86400, immutable"}
    return StreamingResponse(fh, media_type=media_type, headers=headers)
