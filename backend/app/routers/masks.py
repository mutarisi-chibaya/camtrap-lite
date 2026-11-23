"""Camera masks: polygons whose detections are ignored (e.g. grass that waves in the wind)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db import DbSession
from app.deps import WriteAuth
from app.models import Camera, CameraMask, Detection, Image
from app.schemas import CameraBox, ImageOut, MaskCreate, MaskOut
from app.services.masks import is_masked, load_masks
from app.services.pipeline import post_process_camera

router = APIRouter(tags=["masks"])


def _camera(db: DbSession, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


@router.get("/cameras/{camera_id}/masks", response_model=list[MaskOut])
def list_masks(camera_id: int, db: DbSession) -> list[CameraMask]:
    _camera(db, camera_id)
    return list(
        db.scalars(
            select(CameraMask).where(CameraMask.camera_id == camera_id).order_by(CameraMask.id)
        )
    )


@router.post(
    "/cameras/{camera_id}/masks", response_model=MaskOut, status_code=201, dependencies=[WriteAuth]
)
def create_mask(camera_id: int, body: MaskCreate, db: DbSession) -> CameraMask:
    """Add a mask, then re-run the static finder and triage for the camera."""
    _camera(db, camera_id)
    mask = CameraMask(camera_id=camera_id, name=body.name, polygon=[list(p) for p in body.polygon])
    db.add(mask)
    db.flush()
    post_process_camera(db, camera_id)  # commits
    return mask


@router.delete("/masks/{mask_id}", status_code=204, dependencies=[WriteAuth])
def delete_mask(mask_id: int, db: DbSession) -> None:
    mask = db.get(CameraMask, mask_id)
    if mask is None:
        raise HTTPException(status_code=404, detail="mask not found")
    camera_id = mask.camera_id
    db.delete(mask)
    db.flush()
    post_process_camera(db, camera_id)


@router.get("/cameras/{camera_id}/images", response_model=list[ImageOut])
def list_camera_images(
    camera_id: int,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Image]:
    _camera(db, camera_id)
    q = (
        select(Image)
        .where(Image.camera_id == camera_id)
        .order_by(Image.timestamp, Image.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(q))


@router.get("/cameras/{camera_id}/boxes", response_model=list[CameraBox])
def camera_boxes(
    camera_id: int,
    db: DbSession,
    min_conf: Annotated[float, Query(ge=0, le=1)] = 0.2,
    limit: Annotated[int, Query(ge=1, le=10000)] = 5000,
) -> list[CameraBox]:
    """Every detection box of a camera, so the mask editor can show where boxes pile up."""
    _camera(db, camera_id)
    polygons = load_masks(db, [camera_id]).get(camera_id, [])
    dets = db.scalars(
        select(Detection)
        .join(Image)
        .where(Image.camera_id == camera_id, Detection.confidence >= min_conf)
        .order_by(Detection.confidence.desc())
        .limit(limit)
    )
    return [
        CameraBox(
            image_id=d.image_id,
            category=d.category.value,
            confidence=d.confidence,
            bbox=(d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h),
            is_masked=is_masked((d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h), polygons),
        )
        for d in dets
    ]
