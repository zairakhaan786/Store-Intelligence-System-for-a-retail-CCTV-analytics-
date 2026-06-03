"""
Pipeline router — trigger pipeline runs and seeding operations.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session

from src.api.models.database import get_db
from src.api.models.schemas import PipelineRunRequest, PipelineRunResponse
from src.shared.logger import get_logger

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = get_logger(__name__)

_pipeline_running = False


@router.post("/run", response_model=PipelineRunResponse, summary="Trigger pipeline")
async def run_pipeline(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PipelineRunResponse:
    """
    Trigger the detection pipeline.
    Synthetic data generation has been disabled. Please use /upload-video to process CCTV footage.
    """
    raise HTTPException(status_code=400, detail="Synthetic data generation is disabled. Please use the /upload-video endpoint with actual CCTV footage.")



@router.get("/status", summary="Pipeline status")
async def get_status() -> dict:
    """Return current pipeline execution status."""
    return {
        "running": _pipeline_running,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.post("/seed", summary="Seed database with synthetic data")
async def seed_database(
    n_visitors: int = 127,
    db: Session = Depends(get_db),
) -> dict:
    """Seed the database with synthetic visitor data for demonstration."""
    import random
    import uuid
    from sqlalchemy import text
    from datetime import datetime, timedelta, timezone

    db.execute(text("DELETE FROM events"))
    db.execute(text("DELETE FROM sessions"))
    db.execute(text("DELETE FROM transactions"))

    now = datetime.now(timezone.utc)
    for i in range(n_visitors):
        vid = f"VISITOR_{i:04d}"
        sid = str(uuid.uuid4())
        
        db.execute(text("INSERT INTO sessions (id, track_id, session_index, entry_time, is_staff, is_complete, metadata) VALUES (:id, :track_id, 0, :entry, 0, 1, '{}')"), 
                   {"id": sid, "track_id": vid, "entry": now.isoformat()})
                   
        db.execute(text("INSERT INTO events (id, store_id, camera_id, visitor_id, session_id, event_type, timestamp, zone_id, is_staff, confidence, metadata) VALUES (:id, 'STORE_BLR_002', 'CAM_01', :vid, :sid, 'entry', :ts, 'ENTRY_MAIN', 0, 1.0, '{}')"), 
                   {"id": str(uuid.uuid4()), "vid": vid, "sid": sid, "ts": now.isoformat()})

        if random.random() < 0.6:
            db.execute(text("INSERT INTO events (id, store_id, camera_id, visitor_id, session_id, event_type, timestamp, zone_id, is_staff, confidence, metadata) VALUES (:id, 'STORE_BLR_002', 'CAM_01', :vid, :sid, 'zone_enter', :ts, 'AISLE_A', 0, 1.0, '{}')"), 
                       {"id": str(uuid.uuid4()), "vid": vid, "sid": sid, "ts": now.isoformat()})
            
        if random.random() < 0.4:
            db.execute(text("INSERT INTO events (id, store_id, camera_id, visitor_id, session_id, event_type, timestamp, zone_id, is_staff, confidence, metadata) VALUES (:id, 'STORE_BLR_002', 'CAM_01', :vid, :sid, 'zone_enter', :ts, 'CHECKOUT', 0, 1.0, '{}')"), 
                       {"id": str(uuid.uuid4()), "vid": vid, "sid": sid, "ts": now.isoformat()})

    for i in range(53):
        db.execute(text("INSERT INTO transactions (order_id, store_id, order_date, order_time, total_amount) VALUES (:id, 'STORE_BLR_002', :d, :t, 45.0)"),
                   {"id": str(uuid.uuid4()), "d": now.strftime('%Y-%m-%d'), "t": now.strftime('%H:%M:%S')})
                   
    db.commit()
    return {"status": "success", "message": f"Database seeded with {n_visitors} synthetic visitors"}


@router.post("/upload-video", summary="Upload a CCTV video to process")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    camera_id: str = "CAM_01",
    db: Session = Depends(get_db),
) -> dict:
    """
    Upload a CCTV video file and run the detection & tracking pipeline on it.
    The processing runs in the background and populates the database with events.
    """
    import shutil
    import time
    from pathlib import Path
    from sqlalchemy import text

    if not file.filename.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
        raise HTTPException(status_code=400, detail="Invalid video format. Supported formats: .mp4, .avi, .mov, .mkv")
    
    # ── Reset Database for each video ─────────────────────────────────────
    try:
        db.execute(text("DELETE FROM events"))
        db.execute(text("DELETE FROM sessions"))
        db.execute(text("DELETE FROM occupancy"))
        db.execute(text("DELETE FROM anomalies"))
        db.execute(text("DELETE FROM metrics_snapshot"))
        db.commit()
        logger.info("[INFO] Database reset: old events, sessions, occupancy, anomalies, and snapshots cleared.")
    except Exception as exc:
        db.rollback()
        logger.error("Database reset failed", error=str(exc))

    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitize filename
    safe_name = "".join([c if c.isalnum() or c in (".", "_", "-") else "_" for c in file.filename])
    file_path = upload_dir / f"{camera_id}_{int(time.time())}_{safe_name}"
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    logger.info("Video uploaded successfully", path=str(file_path))
    
    def _run_pipeline_task():
        from src.pipeline.video_pipeline import VideoPipeline
        from src.shared.config import settings
        try:
            logger.info("Starting VideoPipeline on uploaded file", path=str(file_path))
            pipeline = VideoPipeline(
                camera_id=camera_id,
                source=str(file_path),
                db_url=settings.database_url,
                enable_face=True,
                enable_display=False,
                skip_frames=2
            )
            result = pipeline.run()
            logger.info("VideoPipeline completed on uploaded file", result=result)
        except Exception as exc:
            logger.error("VideoPipeline execution failed", error=str(exc))
            
    background_tasks.add_task(_run_pipeline_task)
    
    return {
        "status": "uploaded_and_queued",
        "filename": file.filename,
        "saved_path": str(file_path),
        "message": f"Processing started for camera {camera_id} in the background. Database tables cleared."
    }


from fastapi.responses import FileResponse

@router.get("/video/{camera_id}", summary="Get processed video feed")
async def get_processed_video(camera_id: str):
    """Serve the latest annotated processed video file for the given camera."""
    from pathlib import Path
    processed_dir = Path("data/processed")
    video_path = processed_dir / f"{camera_id}_processed.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"No processed video found for camera {camera_id}")
    return FileResponse(str(video_path), media_type="video/mp4")


@router.post("/upload-sales", summary="Upload a store sales transaction CSV")
async def upload_sales(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """
    Upload a sales transaction CSV and ingest it to the transactions database table.
    Correlates visitor counts with sales revenue.
    """
    import shutil
    import time
    from pathlib import Path
    from src.pipeline.csv_processor import ingest_sales_csv
    from src.shared.config import settings

    if not file.filename.lower().endswith((".csv", ".tsv")):
        raise HTTPException(status_code=400, detail="Invalid sales file format. Supported formats: .csv, .tsv")
    
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    safe_name = "".join([c if c.isalnum() or c in (".", "_", "-") else "_" for c in file.filename])
    file_path = upload_dir / f"sales_{int(time.time())}_{safe_name}"
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    logger.info("Sales file uploaded successfully", path=str(file_path))
    
    try:
        count = ingest_sales_csv(str(file_path), db_url=settings.database_url)
        return {
            "status": "success",
            "filename": file.filename,
            "rows_ingested": count,
            "message": f"Successfully ingested {count} sales transactions."
        }
    except Exception as exc:
        logger.error("Sales ingestion failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")
