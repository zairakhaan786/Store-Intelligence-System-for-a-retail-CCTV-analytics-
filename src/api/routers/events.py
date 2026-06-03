"""Events router — /events endpoint."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.models.database import get_db
from src.api.models.schemas import EventListResponse
from src.api.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"])

@router.get("", response_model=EventListResponse, summary="List detection events")
async def list_events(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=500, description="Events per page"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
    zone_id: Optional[str] = Query(default=None, description="Filter by zone"),
    camera_id: Optional[str] = Query(default=None, description="Filter by camera"),
    db: Session = Depends(get_db),
) -> EventListResponse:
    """
    Paginated event log with optional filters.
    """
    svc = EventService(db)
    return svc.list_events(page, page_size, event_type, zone_id, camera_id)
