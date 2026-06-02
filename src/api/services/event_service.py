"""Event service — CRUD operations for events and anomalies."""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.models.database import AnomalyModel, EventModel
from src.api.models.schemas import AnomalyListResponse, AnomalyOut, EventListResponse, EventOut
from src.shared.logger import get_logger

logger = get_logger(__name__)


class EventService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_events(
        self,
        page: int = 1,
        page_size: int = 50,
        event_type: Optional[str] = None,
        zone_id: Optional[str] = None,
        camera_id: Optional[str] = None,
    ) -> EventListResponse:
        db = self._db
        try:
            q = db.query(EventModel)
            if event_type:
                q = q.filter(EventModel.event_type == event_type)
            if zone_id:
                q = q.filter(EventModel.zone_id == zone_id)
            if camera_id:
                q = q.filter(EventModel.camera_id == camera_id)

            total = q.count()
            events = (
                q.order_by(EventModel.timestamp.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return EventListResponse(
                events=[EventOut.model_validate(e) for e in events],
                total=total,
                page=page,
                page_size=page_size,
            )
        except Exception as exc:
            logger.error("Event list failed", error=str(exc))
            return EventListResponse(events=[], total=0, page=page, page_size=page_size)

    def list_anomalies(
        self,
        active_only: bool = True,
        severity: Optional[str] = None,
    ) -> AnomalyListResponse:
        db = self._db
        try:
            q = db.query(AnomalyModel)
            if active_only:
                q = q.filter(AnomalyModel.is_active == True)
            if severity:
                q = q.filter(AnomalyModel.severity == severity)

            total = q.count()
            active_count = db.query(AnomalyModel).filter(AnomalyModel.is_active == True).count()
            anomalies = q.order_by(AnomalyModel.detected_at.desc()).limit(100).all()

            # Also get anomaly events from events table
            anomaly_events = db.execute(
                text("""
                    SELECT id, event_type as anomaly_type, zone_id, track_id,
                           timestamp as detected_at, metadata, created_at
                    FROM events
                    WHERE event_type = 'anomaly'
                    ORDER BY timestamp DESC
                    LIMIT 50
                """)
            ).fetchall()

            # Convert event-based anomalies
            import json
            event_anomalies = []
            for ev in anomaly_events:
                meta = ev.metadata
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                meta = meta or {}
                event_anomalies.append(AnomalyOut(
                    id=ev.id,
                    anomaly_type=meta.get("anomaly_type", "unknown"),
                    severity=meta.get("severity", "medium"),
                    zone_id=ev.zone_id,
                    track_id=ev.track_id,
                    description=meta.get("description", ""),
                    metadata=meta,
                    detected_at=ev.detected_at,
                    resolved_at=None,
                    is_active=True,
                ))

            all_anomalies = [AnomalyOut.model_validate(a) for a in anomalies] + event_anomalies

            return AnomalyListResponse(
                anomalies=all_anomalies,
                total=len(all_anomalies),
                active_count=active_count + len(event_anomalies),
            )
        except Exception as exc:
            logger.error("Anomaly list failed", error=str(exc))
            return AnomalyListResponse(anomalies=[], total=0, active_count=0)
