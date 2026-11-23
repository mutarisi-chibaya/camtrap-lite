"""FastAPI application entry point. OpenAPI docs are served at /docs."""

from fastapi import FastAPI
from sqlalchemy import text

from app.db import DbSession

app = FastAPI(
    title="CamTrap Lite",
    description="Camera-trap processing: MegaDetector, event grouping, triage and human review.",
    version="0.1.0",
)


@app.get("/health", tags=["meta"])
def health(db: DbSession) -> dict[str, str]:
    """Liveness + database connectivity check."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
