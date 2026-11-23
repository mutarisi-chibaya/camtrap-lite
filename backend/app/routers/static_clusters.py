"""Human confirmation of static false-detection clusters (the Static Check page)."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import DbSession
from app.deps import WriteAuth
from app.models import Camera, Detection, StaticCluster, StaticClusterStatus
from app.schemas import StaticClusterOut, StaticClusterUpdate, StaticSample
from app.services.triage import triage_camera

router = APIRouter(prefix="/static-clusters", tags=["static"])

SAMPLES = 8


def _samples(detections: list[Detection], n: int = SAMPLES) -> list[StaticSample]:
    """`n` member detections spread evenly over time, so the reviewer sees the box under
    different light and conditions rather than one burst."""
    dets = sorted(detections, key=lambda d: (d.image.timestamp is None, d.image.timestamp, d.id))
    if len(dets) > n:
        step = len(dets) / n
        dets = [dets[int(i * step)] for i in range(n)]
    return [
        StaticSample(
            image_id=d.image_id,
            detection_id=d.id,
            bbox=(d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h),
            confidence=d.confidence,
            category=d.category.value,
            timestamp=d.image.timestamp,
            width=d.image.width,
            height=d.image.height,
        )
        for d in dets
    ]


def _to_out(cluster: StaticCluster, camera_name: str) -> StaticClusterOut:
    return StaticClusterOut(
        id=cluster.id,
        camera_id=cluster.camera_id,
        camera_name=camera_name,
        bbox=(cluster.bbox_x, cluster.bbox_y, cluster.bbox_w, cluster.bbox_h),
        occurrence_count=cluster.occurrence_count,
        occurrence_fraction=cluster.occurrence_fraction,
        status=cluster.status,
        samples=_samples(cluster.detections),
    )


@router.get("", response_model=list[StaticClusterOut])
def list_clusters(
    db: DbSession,
    camera_id: int | None = None,
    status: StaticClusterStatus | None = None,
) -> list[StaticClusterOut]:
    q = (
        select(StaticCluster, Camera.name)
        .join(Camera, Camera.id == StaticCluster.camera_id)
        .options(selectinload(StaticCluster.detections).selectinload(Detection.image))
        .order_by(StaticCluster.camera_id, StaticCluster.occurrence_count.desc())
    )
    if camera_id is not None:
        q = q.where(StaticCluster.camera_id == camera_id)
    if status is not None:
        q = q.where(StaticCluster.status == status)
    return [_to_out(c, name) for c, name in db.execute(q).all()]


@router.post("/{cluster_id}", response_model=StaticClusterOut, dependencies=[WriteAuth])
def set_cluster_status(
    cluster_id: int, body: StaticClusterUpdate, db: DbSession
) -> StaticClusterOut:
    """Confirm or reject a cluster, then re-run triage for its camera.

    Confirming makes triage ignore the cluster's detections (events that only had the
    "rock" become auto-empty); rejecting or resetting to pending makes them count again.
    """
    cluster = db.get(StaticCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="static cluster not found")
    cluster.status = body.status
    db.flush()
    triage_camera(db, cluster.camera_id)
    db.commit()
    camera = db.get_one(Camera, cluster.camera_id)
    cluster = db.scalars(
        select(StaticCluster)
        .where(StaticCluster.id == cluster_id)
        .options(selectinload(StaticCluster.detections).selectinload(Detection.image))
    ).one()
    return _to_out(cluster, camera.name)
