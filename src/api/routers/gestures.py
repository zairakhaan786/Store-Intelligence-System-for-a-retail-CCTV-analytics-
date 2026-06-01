"""Gesture events router — /gesture-events endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.api.models.database import get_db
from src.shared.logger import get_logger

router = APIRouter(prefix="/gesture-events", tags=["gestures"])
logger = get_logger(__name__)


@router.get("", summary="List gesture interaction events")
async def list_gesture_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    gesture_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return gesture interaction events captured by the gesture control system.

    Gesture types: open_palm, point_select, swipe_left, swipe_right,
                   zoom_in, zoom_out, thumbs_up, fist
    """
    try:
        # Gesture events are stored in events table with event_type='gesture_triggered'
        # and metadata containing gesture_type
        where_clause = "WHERE e.event_type = 'gesture_triggered'"
        params: dict = {}

        if gesture_type:
            where_clause += " AND e.metadata->>'gesture_type' = :gesture_type"
            params["gesture_type"] = gesture_type

        total = db.execute(
            text(f"SELECT COUNT(*) FROM events e {where_clause}"), params
        ).scalar() or 0

        rows = db.execute(
            text(f"""
                SELECT e.id, e.timestamp, e.confidence, e.metadata
                FROM events e
                {where_clause}
                ORDER BY e.timestamp DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).fetchall()

        gestures = []
        for r in rows:
            meta = r.metadata or {}
            gestures.append({
                "id": str(r.id),
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "gesture_type": meta.get("gesture_type", "unknown"),
                "confidence": r.confidence,
                "hand_count": meta.get("hand_count", 1),
                "action_triggered": meta.get("action_triggered"),
            })

        # Summary stats
        gesture_counts = db.execute(
            text("""
                SELECT
                    metadata->>'gesture_type' AS gesture_type,
                    COUNT(*) AS cnt
                FROM events
                WHERE event_type = 'gesture_triggered'
                GROUP BY metadata->>'gesture_type'
                ORDER BY cnt DESC
            """)
        ).fetchall()

        return {
            "gestures": gestures,
            "total": total,
            "page": page,
            "page_size": page_size,
            "gesture_summary": {r.gesture_type: r.cnt for r in gesture_counts},
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Gesture events query failed", error=str(exc))
        return {
            "gestures": [], "total": 0, "page": page,
            "page_size": page_size, "gesture_summary": {},
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }


@router.post("/trigger", summary="Record a gesture event (from gesture controller)")
async def trigger_gesture(
    gesture_type: str,
    confidence: float = 0.9,
    hand_count: int = 1,
    db: Session = Depends(get_db),
) -> dict:
    """
    Record a gesture interaction event.
    Called by the gesture controller when a gesture is detected.
    """
    import uuid
    try:
        import json
        db.execute(
            text("""
                INSERT INTO events (id, event_type, track_id, camera_id, zone_id,
                    timestamp, confidence, metadata)
                VALUES (:id, 'gesture_triggered', 'GESTURE_USER', 'WEBCAM', NULL,
                    NOW(), :confidence, :metadata::jsonb)
            """),
            {
                "id": str(uuid.uuid4()),
                "confidence": confidence,
                "metadata": json.dumps({
                    "gesture_type": gesture_type,
                    "hand_count": hand_count,
                    "action_triggered": _map_gesture_to_action(gesture_type),
                }),
            }
        )
        db.commit()
        return {
            "status": "recorded",
            "gesture_type": gesture_type,
            "action": _map_gesture_to_action(gesture_type),
        }
    except Exception as exc:
        logger.error("Gesture trigger failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}


def _map_gesture_to_action(gesture_type: str) -> str:
    actions = {
        "swipe_left": "navigate_next_panel",
        "swipe_right": "navigate_prev_panel",
        "zoom_in": "expand_view",
        "zoom_out": "collapse_view",
        "open_palm": "pause_stream",
        "point_select": "select_zone",
        "thumbs_up": "confirm_action",
        "fist": "dismiss",
    }
    return actions.get(gesture_type, "unknown_action")
