"""
Pipeline router — trigger pipeline runs and seeding operations.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.models.database import get_db
from src.api.models.schemas import PipelineRunRequest, PipelineRunResponse
from src.shared.logger import get_logger

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = get_logger(__name__)

_pipeline_running = False


def _run_synthetic_pipeline(n_visitors: int = 30) -> int:
    """Run a synthetic pipeline pass (used when no video is available)."""
    from src.pipeline.csv_processor import generate_synthetic_events
    from src.shared.config import settings
    count = generate_synthetic_events(db_url=settings.database_url, n_visitors=n_visitors)
    return count


@router.post("/run", response_model=PipelineRunResponse, summary="Trigger pipeline")
async def run_pipeline(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PipelineRunResponse:
    """
    Trigger the detection pipeline on sample/synthetic data.

    In production this would process a live RTSP stream.
    For demo purposes, it generates synthetic events and stores them.
    """
    global _pipeline_running
    if _pipeline_running:
        raise HTTPException(status_code=409, detail="Pipeline already running")

    _pipeline_running = True

    def _task():
        global _pipeline_running
        try:
            n = max(5, request.duration_seconds // 2)
            _run_synthetic_pipeline(n_visitors=n)
        finally:
            _pipeline_running = False

    background_tasks.add_task(_task)

    return PipelineRunResponse(
        status="started",
        events_generated=0,
        camera_id=request.camera_id,
        duration_seconds=request.duration_seconds,
        message=f"Pipeline started for camera {request.camera_id}. Events will be generated in background.",
    )


@router.get("/status", summary="Pipeline status")
async def get_status() -> dict:
    """Return current pipeline execution status."""
    return {
        "running": _pipeline_running,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.post("/seed", summary="Seed database with synthetic data")
async def seed_database(
    n_visitors: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    """Seed the database with synthetic visitor data for demonstration."""
    try:
        count = _run_synthetic_pipeline(n_visitors=n_visitors)
        return {
            "status": "success",
            "events_generated": count,
            "visitors": n_visitors,
            "message": "Database seeded with synthetic event data",
        }
    except Exception as exc:
        logger.error("Seeding failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Seeding failed: {exc}")
