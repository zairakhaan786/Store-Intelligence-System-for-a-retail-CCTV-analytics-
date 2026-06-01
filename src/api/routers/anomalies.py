"""Anomalies router — /anomalies endpoint."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.models.database import get_db
from src.api.models.schemas import AnomalyListResponse
from src.api.services.event_service import EventService

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", response_model=AnomalyListResponse, summary="List anomalies")
async def list_anomalies(
    active_only: bool = Query(default=True, description="Show only active anomalies"),
    severity: Optional[str] = Query(default=None, description="Filter by severity: low|medium|high|critical"),
    db: Session = Depends(get_db),
) -> AnomalyListResponse:
    """
    Return detected anomalies.

    Anomaly types:
    - overcrowding: zone > 90% capacity for > 60s
    - loitering: person at entry/exit for > 120s
    - long_dwell: person at checkout for > 300s
    - tailgating: ≥2 persons entering within 1.5s
    - group_entry: ≥3 persons entering within 2s
    """
    svc = EventService(db)
    return svc.list_anomalies(active_only, severity)
