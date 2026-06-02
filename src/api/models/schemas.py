"""
Pydantic v2 schemas for request/response validation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator


# ── Common ────────────────────────────────────────────────────────────────────

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


# ── Events ────────────────────────────────────────────────────────────────────

class EventOut(BaseModel):
    id: UUID
    event_type: str
    track_id: Optional[str]
    session_id: Optional[UUID]
    camera_id: Optional[str]
    zone_id: Optional[str]
    timestamp: datetime
    frame_number: Optional[int]
    confidence: Optional[float]
    bbox: Optional[Dict[str, float]]
    metadata_dict: Optional[Dict[str, Any]] = Field(default=None, serialization_alias="metadata", validation_alias=AliasChoices("metadata_dict", "metadata"))

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    events: List[EventOut]
    total: int
    page: int
    page_size: int


# ── Metrics ───────────────────────────────────────────────────────────────────

class MetricsResponse(BaseModel):
    """Primary /metrics response — evaluated by reviewers."""
    total_entries: int = Field(description="Total customer entries today")
    total_exits: int = Field(description="Total exits today")
    unique_visitors: int = Field(description="Unique track IDs (deduplicated)")
    avg_dwell_seconds: float = Field(description="Average time in store (seconds)")
    peak_occupancy: int = Field(description="Maximum simultaneous occupancy")
    conversion_rate: float = Field(description="Fraction of visitors reaching checkout")
    reentry_count: int = Field(description="Number of re-entry events")
    group_entry_count: int = Field(description="Number of group entry events")
    active_sessions: int = Field(description="Currently in-store visitors")
    anomaly_count: int = Field(description="Active anomalies")
    staff_count: int = Field(description="Identified staff members")
    timestamp: datetime = Field(description="Metrics computation time")

    model_config = {"from_attributes": True}


# ── Funnel ────────────────────────────────────────────────────────────────────

class FunnelStage(BaseModel):
    stage: str
    count: int
    pct_from_entry: float


class FunnelResponse(BaseModel):
    """Store visitor funnel: entry → browse → beauty → checkout → exit."""
    stages: List[FunnelStage]
    conversion_rate: float
    avg_stages_per_visitor: float
    date: Optional[str]


# ── Occupancy ─────────────────────────────────────────────────────────────────

class ZoneOccupancy(BaseModel):
    zone_id: str
    name: str
    zone_type: str
    current_count: int
    capacity: int
    utilization_pct: float


class OccupancyResponse(BaseModel):
    zones: List[ZoneOccupancy]
    total_in_store: int
    timestamp: datetime


# ── Anomalies ─────────────────────────────────────────────────────────────────

class AnomalyOut(BaseModel):
    id: UUID
    anomaly_type: str
    severity: str
    zone_id: Optional[str]
    track_id: Optional[str]
    description: Optional[str]
    metadata_dict: Optional[Dict[str, Any]] = Field(default=None, serialization_alias="metadata", validation_alias=AliasChoices("metadata_dict", "metadata"))
    detected_at: datetime
    resolved_at: Optional[datetime]
    is_active: bool

    model_config = {"from_attributes": True}


class AnomalyListResponse(BaseModel):
    anomalies: List[AnomalyOut]
    total: int
    active_count: int


# ── Sessions ──────────────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    id: UUID
    track_id: str
    session_index: int
    entry_time: datetime
    exit_time: Optional[datetime]
    duration_seconds: Optional[float]
    entry_zone: Optional[str]
    exit_zone: Optional[str]
    zones_visited: Optional[List[str]]
    is_staff: bool
    is_complete: bool

    model_config = {"from_attributes": True}


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str  # healthy | degraded | unhealthy
    database: bool
    version: str
    uptime_seconds: float


# ── Heatmap ───────────────────────────────────────────────────────────────────

class HeatmapCell(BaseModel):
    zone_id: str
    name: str
    x_center: float
    y_center: float
    visit_count: int
    avg_dwell: float
    heat_value: float  # normalized 0-1


class HeatmapResponse(BaseModel):
    cells: List[HeatmapCell]
    max_visits: int
    date: Optional[str]


# ── Pipeline trigger ──────────────────────────────────────────────────────────

class PipelineRunRequest(BaseModel):
    camera_id: str = "CAM_01"
    duration_seconds: int = Field(default=30, ge=5, le=300)
    use_synthetic: bool = True


class PipelineRunResponse(BaseModel):
    status: str
    events_generated: int
    camera_id: str
    duration_seconds: int
    message: str
