"""Event triage (auto_animal / auto_empty / needs_review). Implemented in Milestone 3."""

from sqlalchemy.orm import Session


def triage_camera(db: Session, camera_id: int) -> None:
    """Placeholder until Milestone 3."""
