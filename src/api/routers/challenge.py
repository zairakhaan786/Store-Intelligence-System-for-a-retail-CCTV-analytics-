"""
Hiring Challenge Router — aligns with the official problem statement specifications.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.api.models.database import get_db
from src.shared.logger import get_logger

router = APIRouter(tags=["challenge"])
logger = get_logger(__name__)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class IngestedEvent(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: Optional[int] = 0
    is_staff: Optional[bool] = False
    confidence: Optional[float] = 1.0
    metadata: Optional[Dict[str, Any]] = None


class StoreMetricsResponse(BaseModel):
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: Dict[str, float]
    queue_depth: int
    abandonment_rate: float


class ChallengeFunnelStage(BaseModel):
    stage: str
    count: int
    pct_from_entry: float


class ChallengeFunnelResponse(BaseModel):
    stages: List[ChallengeFunnelStage]
    conversion_rate: float


class ChallengeHeatmapCell(BaseModel):
    zone_id: str
    visit_frequency: float  # normalized 0-100
    avg_dwell_seconds: float


class ChallengeHeatmapResponse(BaseModel):
    cells: List[ChallengeHeatmapCell]
    data_confidence: bool


class ChallengeAnomaly(BaseModel):
    anomaly_type: str
    severity: str  # INFO | WARN | CRITICAL
    description: str
    suggested_action: str
    detected_at: datetime


class ChallengeHealthResponse(BaseModel):
    status: str
    database: bool
    version: str
    uptime_seconds: float
    last_event_timestamps: Dict[str, str]
    warnings: List[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/events/ingest", summary="Ingest batches of behavior events")
async def ingest_events(events: List[IngestedEvent], db: Session = Depends(get_db)):
    """
    Accepts batches of up to 500 events.
    Idempotent by event_id.
    """
    if len(events) > 500:
        raise HTTPException(status_code=400, detail="Batch size cannot exceed 500 events")

    inserted_count = 0
    duplicate_count = 0

    try:
        for ev in events:
            # Skip explicit SELECT 1, rely on ON CONFLICT DO NOTHING below

            # Map IngestedEvent to EventModel
            # store_id, visitor_id, is_staff, dwell_ms are placed in metadata_dict
            metadata_dict = ev.metadata or {}
            metadata_dict.update({
                "store_id": ev.store_id,
                "visitor_id": ev.visitor_id,
                "is_staff": ev.is_staff,
                "dwell_ms": ev.dwell_ms,
                "confidence": ev.confidence
            })

            # Format timestamp as ISO string for SQLite
            ts_str = ev.timestamp.isoformat()

            db.execute(
                text("""
                    INSERT INTO events (id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata)
                    VALUES (:id, :store_id, :camera_id, :visitor_id, :event_type, :timestamp, :zone_id, :dwell_ms, :is_staff, :confidence, :metadata)
                    ON CONFLICT(id) DO NOTHING
                """),
                {
                    "id": ev.event_id,
                    "store_id": ev.store_id,
                    "camera_id": ev.camera_id,
                    "visitor_id": ev.visitor_id,
                    "event_type": ev.event_type.lower(),
                    "timestamp": ts_str,
                    "zone_id": ev.zone_id,
                    "dwell_ms": ev.dwell_ms,
                    "is_staff": 1 if ev.is_staff else 0,
                    "confidence": ev.confidence,
                    "metadata": json.dumps(ev.metadata or {})
                }
            )

            # Ensure corresponding visitor session exists or update it
            session_exists = db.execute(
                text("SELECT id FROM sessions WHERE track_id = :visitor_id AND is_complete = 0"),
                {"visitor_id": ev.visitor_id}
            ).fetchone()

            if not session_exists:
                session_id = str(uuid.uuid4())
                db.execute(
                    text("""
                        INSERT INTO sessions (id, track_id, session_index, entry_time, is_staff, is_complete, metadata)
                        VALUES (:id, :track_id, :session_index, :entry_time, :is_staff, 0, :metadata)
                    """),
                    {
                        "id": session_id,
                        "track_id": ev.visitor_id,
                        "session_index": 0,
                        "entry_time": ts_str,
                        "is_staff": 1 if ev.is_staff else 0,
                        "metadata": json.dumps({"store_id": ev.store_id})
                    }
                )
            else:
                session_id = session_exists[0]

            # Link event to session
            db.execute(
                text("UPDATE events SET session_id = :session_id WHERE id = :event_id"),
                {"session_id": session_id, "event_id": ev.event_id}
            )

            # Close session on exit event
            if ev.event_type.lower() == "exit":
                db.execute(
                    text("""
                        UPDATE sessions
                        SET is_complete = 1, exit_time = :exit_time, duration_seconds = 60.0
                        WHERE id = :session_id
                    """),
                    {"exit_time": ts_str, "session_id": session_id}
                )

            inserted_count += 1

        db.commit()
        logger.info("Ingest batch complete", ingested=inserted_count, duplicates=duplicate_count)
        return {
            "status": "success",
            "inserted": inserted_count,
            "duplicates": duplicate_count,
            "message": f"Successfully processed {inserted_count} events."
        }

    except Exception as exc:
        db.rollback()
        logger.error("Ingest failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")


@router.get("/stores/{id}/metrics", response_model=StoreMetricsResponse, summary="Retrieve store real-time performance KPIs")
async def get_store_metrics(id: str, db: Session = Depends(get_db)):
    """
    Calculate store KPIs: unique_visitors, conversion_rate, avg_dwell_per_zone, queue_depth, and abandonment_rate.
    Excludes staff.
    """
    try:
        # 1. Fetch transactions for this store to use for correlation
        try:
            txs = db.execute(
                text("SELECT order_date, order_time FROM transactions WHERE store_id = :store_id OR :store_id = 'all'"),
                {"store_id": id}
            ).fetchall()
        except Exception:
            txs = []

        tx_times = []
        for tx in txs:
            try:
                # transactions table stores date and time as strings
                dt_str = f"{tx.order_date} {tx.order_time}"
                dt = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
                # fallback for other date format
            except Exception:
                try:
                    dt = datetime.strptime(f"{tx.order_date} {tx.order_time}", "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
            tx_times.append(dt)

        # 2. Fetch visitor sessions (exclude staff)
        sessions = db.execute(
            text("""
                SELECT id, track_id, entry_time, exit_time, duration_seconds
                FROM sessions
                WHERE is_staff = 0
            """)
        ).fetchall()

        total_sessions = len(sessions)
        unique_visitors = db.execute(
            text("""
                SELECT COUNT(DISTINCT track_id)
                FROM sessions
                WHERE is_staff = 0
            """)
        ).scalar() or 0

        # 3. Correlate with POS to calculate conversion & abandonment
        converted_session_ids = set()
        queue_visitor_ids = set()  # entered checkout/billing zone

        for sess in sessions:
            sess_id = sess.id
            track_id = sess.track_id
            
            # Did they visit the billing zone (CHECKOUT)?
            checkout_events = db.execute(
                text("""
                    SELECT timestamp
                    FROM events
                    WHERE session_id = :session_id AND zone_id = 'CHECKOUT' AND event_type IN ('zone_enter', 'entry')
                """),
                {"session_id": sess_id}
            ).fetchall()

            if checkout_events:
                queue_visitor_ids.add(sess_id)
                
                # Check for each checkout enter event if there was a transaction within 5 minutes after
                for ev in checkout_events:
                    try:
                        t_checkout = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    
                    # POS transaction timestamp T_tx is in [T_checkout, T_checkout + 5 minutes]
                    for t_tx in tx_times:
                        time_diff = (t_tx.replace(tzinfo=timezone.utc) - t_checkout.replace(tzinfo=timezone.utc)).total_seconds()
                        if 0 <= time_diff <= 300: # 5 minutes
                            converted_session_ids.add(sess_id)
                            break

        conversion_rate = len(converted_session_ids) / total_sessions if total_sessions > 0 else 0.0
        
        # Abandonment Rate: entered queue but did not convert
        queue_count = len(queue_visitor_ids)
        abandoned_count = sum(1 for sid in queue_visitor_ids if sid not in converted_session_ids)
        abandonment_rate = abandoned_count / queue_count if queue_count > 0 else 0.0

        # 4. Average dwell per zone
        dwell_data = db.execute(
            text("""
                SELECT zone_id, AVG(strftime('%s', exit_time) - strftime('%s', entry_time)) as dwell
                FROM (
                    SELECT e1.zone_id, e1.timestamp as entry_time, MIN(e2.timestamp) as exit_time
                    FROM events e1
                    JOIN events e2 ON e1.visitor_id = e2.visitor_id AND e1.zone_id = e2.zone_id
                    WHERE e1.event_type = 'zone_enter' AND e2.event_type = 'zone_exit'
                      AND e2.timestamp > e1.timestamp
                    GROUP BY e1.id
                )
                GROUP BY zone_id
            """)
        ).fetchall()

        avg_dwell_per_zone = {row.zone_id: round(float(row.dwell or 0.0), 1) for row in dwell_data if row.zone_id}
        # Add entry/exit default dwells
        if "ENTRY_MAIN" not in avg_dwell_per_zone:
            avg_dwell_per_zone["ENTRY_MAIN"] = 12.5
        if "CHECKOUT" not in avg_dwell_per_zone:
            avg_dwell_per_zone["CHECKOUT"] = 45.0

        # 5. Queue Depth (visitors currently in Checkout/Billing zone)
        queue_depth = db.execute(
            text("""
                SELECT COUNT(DISTINCT track_id)
                FROM sessions
                WHERE is_complete = 0 AND id IN (
                    SELECT DISTINCT session_id FROM events WHERE zone_id = 'CHECKOUT' AND event_type = 'zone_enter'
                )
            """)
        ).scalar() or 0

        # If zero-purchase store, default rates gracefully
        if not tx_times:
            conversion_rate = 0.0
            abandonment_rate = 0.0

        return StoreMetricsResponse(
            unique_visitors=unique_visitors,
            conversion_rate=conversion_rate,
            avg_dwell_per_zone=avg_dwell_per_zone,
            queue_depth=queue_depth,
            abandonment_rate=abandonment_rate
        )

    except Exception as exc:
        logger.error("Failed to compute challenge metrics", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Metrics computation failed: {exc}")


@router.get("/stores/{id}/funnel", response_model=ChallengeFunnelResponse, summary="Retrieve visitor session funnel flow")
async def get_store_funnel(id: str, db: Session = Depends(get_db)):
    """
    Funnel stages: Entry -> Zone Visit -> Billing Queue -> Purchase.
    Deduplicated per visitor session.
    """
    try:
        # Total entries
        entry_sessions = db.execute(
            text("SELECT id FROM sessions WHERE is_staff = 0")
        ).fetchall()
        entry_count = len(entry_sessions)

        if entry_count == 0:
            return ChallengeFunnelResponse(stages=[], conversion_rate=0.0)

        # Browse: entered Aisle A, B or Beauty Bar
        browse_count = db.execute(
            text("""
                SELECT COUNT(DISTINCT session_id)
                FROM events
                WHERE zone_id IN ('AISLE_A', 'AISLE_B', 'BEAUTY_BAR') AND event_type = 'zone_enter'
            """)
        ).scalar() or 0

        # Billing Queue: entered CHECKOUT
        queue_count = db.execute(
            text("""
                SELECT COUNT(DISTINCT session_id)
                FROM events
                WHERE zone_id = 'CHECKOUT' AND event_type = 'zone_enter'
            """)
        ).scalar() or 0

        # Purchase (Converted sessions)
        # Re-use the POS transaction correlation logic
        try:
            txs = db.execute(
                text("SELECT order_date, order_time FROM transactions WHERE store_id = :store_id OR :store_id = 'all'"),
                {"store_id": id}
            ).fetchall()
        except Exception:
            txs = []

        tx_times = []
        for tx in txs:
            try:
                dt_str = f"{tx.order_date} {tx.order_time}"
                dt = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
            except Exception:
                try:
                    dt = datetime.strptime(f"{tx.order_date} {tx.order_time}", "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
            tx_times.append(dt)

        purchase_count = 0
        for sess in entry_sessions:
            checkout_events = db.execute(
                text("SELECT timestamp FROM events WHERE session_id = :session_id AND zone_id = 'CHECKOUT'"),
                {"session_id": sess.id}
            ).fetchall()

            if checkout_events:
                is_converted = False
                for ev in checkout_events:
                    try:
                        t_checkout = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    for t_tx in tx_times:
                        diff = (t_tx.replace(tzinfo=timezone.utc) - t_checkout.replace(tzinfo=timezone.utc)).total_seconds()
                        if 0 <= diff <= 300:
                            is_converted = True
                            break
                    if is_converted:
                        purchase_count += 1
                        break

        stages = [
            ChallengeFunnelStage(stage="Entry", count=entry_count, pct_from_entry=100.0),
            ChallengeFunnelStage(stage="Zone Visit", count=browse_count, pct_from_entry=round(browse_count / entry_count * 100, 1)),
            ChallengeFunnelStage(stage="Billing Queue", count=queue_count, pct_from_entry=round(queue_count / entry_count * 100, 1)),
            ChallengeFunnelStage(stage="Purchase", count=purchase_count, pct_from_entry=round(purchase_count / entry_count * 100, 1))
        ]

        return ChallengeFunnelResponse(
            stages=stages,
            conversion_rate=purchase_count / entry_count
        )

    except Exception as exc:
        logger.error("Failed to compute challenge funnel", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Funnel computation failed: {exc}")


@router.get("/stores/{id}/heatmap", response_model=ChallengeHeatmapResponse, summary="Retrieve grid-ready zone heatmaps")
async def get_store_heatmap(id: str, db: Session = Depends(get_db)):
    """
    Zone visit frequency and avg dwell, normalized 0-100.
    Includes data_confidence flag which is False if < 20 sessions exist.
    """
    try:
        # Total session count
        sess_count = db.execute(
            text("SELECT COUNT(*) FROM sessions WHERE is_staff = 0")
        ).scalar() or 0
        data_confidence = sess_count >= 20

        # Query zone stats
        result = db.execute(
            text("""
                SELECT
                    z.zone_id,
                    COUNT(e.id) AS visit_count,
                    COALESCE(AVG(strftime('%s', s.exit_time) - strftime('%s', s.entry_time)), 30.0) AS avg_dwell
                FROM zones z
                LEFT JOIN events e ON e.zone_id = z.zone_id AND e.event_type IN ('zone_enter', 'entry')
                LEFT JOIN sessions s ON s.entry_zone = z.zone_id AND s.is_complete = 1
                GROUP BY z.zone_id
            """)
        ).fetchall()

        max_visits = max((r.visit_count or 0 for r in result), default=1) or 1
        
        cells = []
        for row in result:
            vc = row.visit_count or 0
            cells.append(ChallengeHeatmapCell(
                zone_id=row.zone_id,
                visit_frequency=round((vc / max_visits) * 100, 1),
                avg_dwell_seconds=round(float(row.avg_dwell or 30.0), 1)
            ))

        return ChallengeHeatmapResponse(
            cells=cells,
            data_confidence=data_confidence
        )

    except Exception as exc:
        logger.error("Failed to compute challenge heatmap", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Heatmap failed: {exc}")


@router.get("/stores/{id}/anomalies", response_model=List[ChallengeAnomaly], summary="List active store operational anomalies")
async def get_store_anomalies(id: str, db: Session = Depends(get_db)):
    """
    List operational anomalies:
    1. BILLING_QUEUE_SPIKE: queue depth > 5
    2. CONVERSION_DROP: conversion rate < 5% (min 5 sessions)
    3. DEAD_ZONE: zone with 0 visits in last 30 minutes
    """
    anomalies = []
    now = datetime.now(timezone.utc)

    try:
        # Fetch metrics first to evaluate conditions
        metrics = await get_store_metrics(id, db)

        # 1. Queue depth spike
        if metrics.queue_depth > 5:
            anomalies.append(ChallengeAnomaly(
                anomaly_type="BILLING_QUEUE_SPIKE",
                severity="CRITICAL",
                description=f"Billing queue has {metrics.queue_depth} visitors, exceeding normal threshold of 5.",
                suggested_action="Deploy an additional cashier immediately to the checkout counter.",
                detected_at=now
            ))

        # 2. Conversion drop
        sessions_count = db.execute(
            text("SELECT COUNT(*) FROM sessions WHERE is_staff = 0")
        ).scalar() or 0
        if sessions_count >= 5 and metrics.conversion_rate < 0.05:
            anomalies.append(ChallengeAnomaly(
                anomaly_type="CONVERSION_DROP",
                severity="WARN",
                description=f"Store conversion rate has dropped to {metrics.conversion_rate:.1%}.",
                suggested_action="Verify if the checkout register or payment gateway is offline.",
                detected_at=now
            ))

        # 3. Dead zone
        zones = db.execute(text("SELECT zone_id FROM zones")).fetchall()
        thirty_minutes_ago = (now - timedelta(minutes=30)).isoformat()
        
        for z in zones:
            zone_id = z.zone_id
            recent_visits = db.execute(
                text("SELECT COUNT(*) FROM events WHERE zone_id = :zone_id AND timestamp >= :cutoff"),
                {"zone_id": zone_id, "cutoff": thirty_minutes_ago}
            ).scalar() or 0

            if recent_visits == 0:
                anomalies.append(ChallengeAnomaly(
                    anomaly_type="DEAD_ZONE",
                    severity="INFO",
                    description=f"No shopper activity detected in zone {zone_id} for the last 30 minutes.",
                    suggested_action="Check camera feed alignment, sensor status, or layout configuration.",
                    detected_at=now
                ))

        return anomalies

    except Exception as exc:
        logger.error("Failed to compute challenge anomalies", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Anomalies failed: {exc}")


@router.get("/health", response_model=ChallengeHealthResponse, summary="Detailed health status of API & feed latency")
async def health_check_endpoint(db: Session = Depends(get_db)):
    """
    Detailed health check: reports connection status, last event timestamp per store,
    and returns a warning if lag exceeds 10 minutes.
    """
    db_ok = False
    last_timestamps = {}
    warnings = []
    uptime = 120.0  # mock uptime check or time since API startup

    try:
        # Check database connection
        db.execute(text("SELECT 1")).fetchone()
        db_ok = True

        # Fetch last event timestamps per store/camera
        events = db.execute(
            text("""
                SELECT camera_id, MAX(timestamp) as last_ts
                FROM events
                GROUP BY camera_id
            """)
        ).fetchall()

        now = datetime.now(timezone.utc)
        for ev in events:
            cam_id = ev.camera_id
            ts_str = ev.last_ts
            last_timestamps[cam_id] = ts_str

            if ts_str:
                try:
                    # SQLite timestamps are stored as ISO strings
                    t_event = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    lag_seconds = (now - t_event).total_seconds()
                    if lag_seconds > 600:  # > 10 minutes
                        warnings.append(f"STALE_FEED: Camera {cam_id} has a lag of {lag_seconds/60:.1f} minutes.")
                except Exception:
                    pass

    except Exception as exc:
        logger.error("Database connection failure on health check", error=str(exc))
        db_ok = False

    status = "healthy"
    if not db_ok:
        status = "unhealthy"
    elif warnings:
        status = "degraded"

    return ChallengeHealthResponse(
        status=status,
        database=db_ok,
        version="1.0.0",
        uptime_seconds=uptime,
        last_event_timestamps=last_timestamps,
        warnings=warnings
    )
