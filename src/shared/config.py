"""
Shared configuration — loaded from environment / .env file.
Uses pydantic-settings so every value is validated at startup.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "store_intelligence"
    postgres_user: str = "retail_admin"
    postgres_password: str = "retail_secret"

    @property
    def database_url(self) -> str:
        import os
        override = os.getenv("DATABASE_URL")
        if override:
            return override
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── API ───────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False
    log_level: str = "INFO"

    # ── Pipeline ──────────────────────────────────────────────
    yolo_model: str = "yolov8n.pt"
    yolo_confidence: float = 0.35
    yolo_iou: float = 0.45
    tracker_max_age: int = 30
    tracker_min_hits: int = 3
    reentry_gap_seconds: int = 30
    group_entry_window_seconds: int = 2
    group_entry_min_size: int = 3
    entry_line_y_ratio: float = 0.85
    exit_line_y_ratio: float = 0.15

    # ── Dashboard ─────────────────────────────────────────────
    streamlit_port: int = 8501
    api_base_url: str = "http://localhost:8000"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
