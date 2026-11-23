"""FastAPI application entry point. OpenAPI docs are served at /docs."""

from fastapi import FastAPI
from sqlalchemy import text

from app.db import DbSession
from app.routers import cameras, images, review, stats

app = FastAPI(
    title="CamTrap Lite",
    description="Camera-trap processing: MegaDetector, event grouping, triage and human review.",
    version="0.1.0",
)
app.include_router(cameras.router)
app.include_router(images.router)
app.include_router(stats.router)
app.include_router(review.router)


@app.get("/health", tags=["meta"])
def health(db: DbSession) -> dict[str, str]:
    """Liveness + database connectivity check."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
