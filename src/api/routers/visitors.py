"""Visitors router — /visitors endpoint for session-level data."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.api.models.database import get_db
from src.api.models.schemas import SessionOut
from src.shared.logger import get_logger

router = APIRouter(prefix="/visitors", tags=["visitors"])
logger = get_logger(__name__)


@router.get("", summary="List visitor sessions")
async def list_visitors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    is_staff: Optional[bool] = Query(default=None),
    is_complete: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return paginated visitor session records.

    Each session represents one store visit (including re-visits with session_index > 0).
    """
    try:
        conditions = []
        params = {}
        if is_staff is not None:
            conditions.append("is_staff = :is_staff")
            params["is_staff"] = is_staff
        if is_complete is not None:
            conditions.append("is_complete = :is_complete")
            params["is_complete"] = is_complete

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        total = db.execute(
            text(f"SELECT COUNT(*) FROM sessions {where}"), params
        ).scalar() or 0

        rows = db.execute(
            text(f"""
                SELECT id, track_id, session_index, entry_time, exit_time,
                       duration_seconds, entry_zone, exit_zone, zones_visited,
                       is_staff, is_complete
                FROM sessions {where}
                ORDER BY entry_time DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).fetchall()

        visitors = []
        for r in rows:
            visitors.append({
                "id": str(r.id),
                "track_id": r.track_id,
                "session_index": r.session_index,
                "entry_time": r.entry_time.isoformat() if r.entry_time else None,
                "exit_time": r.exit_time.isoformat() if r.exit_time else None,
                "duration_seconds": r.duration_seconds,
                "entry_zone": r.entry_zone,
                "exit_zone": r.exit_zone,
                "zones_visited": r.zones_visited if isinstance(r.zones_visited, list) else [],
                "is_staff": r.is_staff,
                "is_complete": r.is_complete,
            })

        return {
            "visitors": visitors,
            "total": total,
            "page": page,
            "page_size": page_size,
            "unique_visitors": db.execute(
                text("SELECT COUNT(DISTINCT track_id) FROM sessions WHERE session_index = 0")
            ).scalar() or 0,
        }
    except Exception as exc:
        logger.error("Visitors query failed", error=str(exc))
        return {"visitors": [], "total": 0, "page": page, "page_size": page_size, "unique_visitors": 0}
