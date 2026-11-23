"""Application settings, read from environment variables (or a `.env` file).

All triage / clustering thresholds live here so they can be shown on the dashboard
and tuned without touching code.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./camtrap.db"
    storage_dir: str = "./data/storage"
    api_key: str | None = None

    # Processing
    batch_size: int = 20
    # Detections below this are not stored (MegaDetector's "conservative" threshold).
    detection_min_conf: float = 0.05

    # Event grouping
    event_gap_seconds: int = 60

    # Static false-detection finder
    static_min_conf: float = 0.2
    static_iou: float = 0.7
    static_min_fraction: float = 0.1
    static_min_count: int = 5

    # Triage
    auto_accept_conf: float = 0.80
    auto_empty_conf: float = 0.10


@lru_cache
def get_settings() -> Settings:
    return Settings()
