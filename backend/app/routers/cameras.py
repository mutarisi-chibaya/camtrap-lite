from fastapi import APIRouter, HTTPException, UploadFile
from sqlalchemy import func, select

from app.db import DbSession
from app.deps import QueueDep, StorageDep, WriteAuth
from app.models import Camera, Image
from app.schemas import CameraCreate, CameraOut, ImageOut, RejectedFile, UploadResult
from app.services.ingest import InvalidImageError, enqueue_detection, ingest_image

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.post("", response_model=CameraOut, status_code=201, dependencies=[WriteAuth])
def create_camera(body: CameraCreate, db: DbSession) -> Camera:
    camera = Camera(**body.model_dump())
    db.add(camera)
    db.commit()
    return camera


@router.get("", response_model=list[CameraOut])
def list_cameras(db: DbSession) -> list[CameraOut]:
    counts = dict(db.execute(select(Image.camera_id, func.count()).group_by(Image.camera_id)).all())
    cameras = db.scalars(select(Camera).order_by(Camera.id)).all()
    return [
        CameraOut.model_validate(c).model_copy(update={"image_count": counts.get(c.id, 0)})
        for c in cameras
    ]


@router.post(
    "/{camera_id}/images", response_model=UploadResult, status_code=201, dependencies=[WriteAuth]
)
def upload_images(
    camera_id: int,
    files: list[UploadFile],
    db: DbSession,
    storage: StorageDep,
    queue: QueueDep,
) -> UploadResult:
    """Store the files, create Image rows and enqueue detection in batches of BATCH_SIZE."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")

    images: list[Image] = []
    rejected: list[RejectedFile] = []
    for f in files:
        name = f.filename or "upload.jpg"
        try:
            images.append(ingest_image(db, storage, camera, name, f.file.read()))
        except InvalidImageError as e:
            rejected.append(RejectedFile(filename=name, reason=str(e)))

    job_ids = enqueue_detection(db, queue, images)
    return UploadResult(
        images=[ImageOut.model_validate(i) for i in images], rejected=rejected, job_ids=job_ids
    )
