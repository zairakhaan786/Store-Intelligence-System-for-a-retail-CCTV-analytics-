"""Metrics router — /metrics endpoint (key store KPI check)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.models.database import get_db
from src.api.models.schemas import FunnelResponse, HeatmapResponse, MetricsResponse, OccupancyResponse
from src.api.services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse, summary="Store KPIs")
async def get_metrics(db: Session = Depends(get_db)) -> MetricsResponse:
    """
    Return aggregated store KPIs:
    - Total entries/exits, unique visitors
    - Average dwell time, peak occupancy
    - Conversion rate (visitors reaching checkout)
    - Re-entry and group entry counts
    - Active anomalies
    """
    svc = MetricsService(db)
    return svc.get_metrics()


@router.get("/funnel", response_model=FunnelResponse, summary="Visitor funnel")
async def get_funnel(db: Session = Depends(get_db)) -> FunnelResponse:
    """
    Return the store visitor funnel showing drop-off at each stage.
    Session-based: each visitor counted once per stage.
    """
    svc = MetricsService(db)
    return svc.get_funnel()


@router.get("/occupancy", response_model=OccupancyResponse, summary="Zone occupancy")
async def get_occupancy(db: Session = Depends(get_db)) -> OccupancyResponse:
    """Return current real-time occupancy per zone."""
    svc = MetricsService(db)
    return svc.get_occupancy()


@router.get("/heatmap", response_model=HeatmapResponse, summary="Zone heatmap data")
async def get_heatmap(db: Session = Depends(get_db)) -> HeatmapResponse:
    """Return heatmap data based on zone visit frequency and dwell time."""
    svc = MetricsService(db)
    return svc.get_heatmap()


@router.get("/sales", summary="Store sales metrics")
async def get_sales_metrics(db: Session = Depends(get_db)) -> dict:
    """Return store sales performance aggregated from uploaded transactions."""
    svc = MetricsService(db)
    return svc.get_sales_metrics()
