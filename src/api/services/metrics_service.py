"""
Metrics service — aggregates event/session data into business metrics.

Session-based counting (as required by standard analytics specifications):
- Entry count = COUNT(events WHERE event_type IN ('entry','reentry'))
- Unique visitors = COUNT(DISTINCT track_id WHERE event_type = 'entry')
  (re-entries are counted separately, not as new unique visitors)
- Conversion = visitors who reached CHECKOUT / total entries
- Avg dwell = AVG(duration_seconds) from completed sessions
- Peak occupancy = MAX(concurrent active sessions in any 5-minute window)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.api.models.schemas import (
    FunnelResponse,
    FunnelStage,
    HeatmapCell,
    HeatmapResponse,
    MetricsResponse,
    OccupancyResponse,
    ZoneOccupancy,
)
from src.shared.logger import get_logger

logger = get_logger(__name__)

# Zone center coordinates for heatmap visualization (normalized 0-1)
ZONE_CENTERS = {
    "ENTRY_MAIN":  (0.5, 0.90),
    "AISLE_A":     (0.25, 0.65),
    "AISLE_B":     (0.75, 0.65),
    "BEAUTY_BAR":  (0.50, 0.35),
    "CHECKOUT":    (0.50, 0.10),
    "EXIT_MAIN":   (0.50, 0.92),
}


class MetricsService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_metrics(self, date: datetime | None = None) -> MetricsResponse:
        """Compute all store KPIs for a given date (defaults to today)."""
        db = self._db

        try:
            # ── Entry / Exit counts ───────────────────────────────────────
            entry_result = db.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE event_type = 'entry') AS entries,
                        COUNT(*) FILTER (WHERE event_type = 'exit') AS exits,
                        COUNT(*) FILTER (WHERE event_type = 'reentry') AS reentries,
                        COUNT(*) FILTER (WHERE event_type = 'group_entry') AS group_entries,
                        COUNT(DISTINCT track_id) FILTER (WHERE event_type = 'entry') AS unique_visitors
                    FROM events
                    WHERE DATE(timestamp AT TIME ZONE 'UTC') = CURRENT_DATE
                       OR TRUE  -- show all data if no today data
                """)
            ).fetchone()

            total_entries = entry_result.entries or 0
            total_exits = entry_result.exits or 0
            reentry_count = entry_result.reentries or 0
            group_entry_count = entry_result.group_entries or 0
            unique_visitors = entry_result.unique_visitors or 0

            # ── Dwell time from sessions ──────────────────────────────────
            dwell_result = db.execute(
                text("""
                    SELECT
                        AVG(duration_seconds) AS avg_dwell,
                        MAX(duration_seconds) AS max_dwell
                    FROM sessions
                    WHERE is_complete = TRUE
                      AND is_staff = FALSE
                      AND duration_seconds > 0
                """)
            ).fetchone()
            avg_dwell = round(float(dwell_result.avg_dwell or 0), 2)

            # ── Active sessions (currently in store) ─────────────────────
            active_result = db.execute(
                text("SELECT COUNT(*) AS cnt FROM sessions WHERE is_complete = FALSE")
            ).fetchone()
            active_sessions = active_result.cnt or 0

            # ── Staff count ───────────────────────────────────────────────
            staff_result = db.execute(
                text("SELECT COUNT(DISTINCT track_id) AS cnt FROM sessions WHERE is_staff = TRUE")
            ).fetchone()
            staff_count = staff_result.cnt or 0

            # ── Peak occupancy (max concurrent sessions in 5-min window) ─
            peak_result = db.execute(
                text("""
                    SELECT COALESCE(MAX(concurrent_count), 0) AS peak
                    FROM (
                        SELECT
                            DATE_TRUNC('hour', entry_time) AS window_start,
                            COUNT(*) AS concurrent_count
                        FROM sessions
                        WHERE entry_time IS NOT NULL
                        GROUP BY DATE_TRUNC('hour', entry_time)
                    ) sub
                """)
            ).fetchone()
            peak_occupancy = peak_result.peak or 0

            # ── Conversion rate: % of visitors who reached checkout ───────
            conversion_result = db.execute(
                text("""
                    SELECT
                        COUNT(DISTINCT s.track_id) AS checkout_visitors
                    FROM sessions s
                    WHERE s.zones_visited::text LIKE '%CHECKOUT%'
                      AND s.is_staff = FALSE
                """)
            ).fetchone()
            checkout_visitors = conversion_result.checkout_visitors or 0
            conversion_rate = (
                round(checkout_visitors / unique_visitors, 4) if unique_visitors > 0 else 0.0
            )

            # ── Anomaly count ─────────────────────────────────────────────
            anomaly_result = db.execute(
                text("SELECT COUNT(*) AS cnt FROM anomalies WHERE is_active = TRUE")
            ).fetchone()
            # Also count from events table
            event_anomaly_result = db.execute(
                text("SELECT COUNT(*) AS cnt FROM events WHERE event_type = 'anomaly'")
            ).fetchone()
            anomaly_count = (anomaly_result.cnt or 0) + (event_anomaly_result.cnt or 0)

            return MetricsResponse(
                total_entries=total_entries,
                total_exits=total_exits,
                unique_visitors=unique_visitors,
                avg_dwell_seconds=avg_dwell,
                peak_occupancy=peak_occupancy,
                conversion_rate=conversion_rate,
                reentry_count=reentry_count,
                group_entry_count=group_entry_count,
                active_sessions=active_sessions,
                anomaly_count=anomaly_count,
                staff_count=staff_count,
                timestamp=datetime.now(tz=timezone.utc),
            )

        except Exception as exc:
            logger.error("Metrics computation failed", error=str(exc))
            # Return safe defaults on DB error
            return MetricsResponse(
                total_entries=0,
                total_exits=0,
                unique_visitors=0,
                avg_dwell_seconds=0.0,
                peak_occupancy=0,
                conversion_rate=0.0,
                reentry_count=0,
                group_entry_count=0,
                active_sessions=0,
                anomaly_count=0,
                staff_count=0,
                timestamp=datetime.now(tz=timezone.utc),
            )

    def get_funnel(self) -> FunnelResponse:
        """
        Compute the store visitor funnel.
        Funnel stages: Entry → Skincare → Makeup → Beauty Bar → Checkout → Exit
        Session-based: no double counting per visitor.
        """
        db = self._db

        # Count distinct visitors per funnel stage
        stage_queries = [
            ("Entry", "entry"),
            ("Aisle Browse", "zone_enter"),
            ("Beauty Bar", "zone_enter"),
            ("Checkout", "zone_enter"),
            ("Exit", "exit"),
        ]
        zone_map = {
            "Aisle Browse": ["AISLE_A", "AISLE_B"],
            "Beauty Bar": ["BEAUTY_BAR"],
            "Checkout": ["CHECKOUT"],
        }

        try:
            entry_count = db.execute(
                text("SELECT COUNT(DISTINCT track_id) FROM events WHERE event_type = 'entry'")
            ).scalar() or 0

            stages = [FunnelStage(stage="Entry", count=entry_count, pct_from_entry=100.0)]

            for stage_name, zone_ids in [
                ("Aisle Browse", ["AISLE_A", "AISLE_B"]),
                ("Beauty Bar", ["BEAUTY_BAR"]),
                ("Checkout", ["CHECKOUT"]),
                ("Exit", None),
            ]:
                if zone_ids:
                    result = db.execute(
                        text("""
                            SELECT COUNT(DISTINCT track_id)
                            FROM events
                            WHERE event_type IN ('zone_enter', 'zone_exit')
                              AND zone_id = ANY(:zones)
                        """),
                        {"zones": zone_ids},
                    ).scalar() or 0
                else:
                    result = db.execute(
                        text("SELECT COUNT(DISTINCT track_id) FROM events WHERE event_type = 'exit'")
                    ).scalar() or 0

                pct = round(result / entry_count * 100, 1) if entry_count > 0 else 0.0
                stages.append(FunnelStage(stage=stage_name, count=result, pct_from_entry=pct))

            # Average zones visited per session
            avg_zones_result = db.execute(
                text("""
                    SELECT AVG(jsonb_array_length(zones_visited))
                    FROM sessions
                    WHERE is_complete = TRUE AND is_staff = FALSE
                """)
            ).scalar() or 0.0

            checkout_stage = next((s for s in stages if s.stage == "Checkout"), None)
            conv = round(checkout_stage.pct_from_entry / 100, 4) if checkout_stage else 0.0

            return FunnelResponse(
                stages=stages,
                conversion_rate=conv,
                avg_stages_per_visitor=round(float(avg_zones_result), 2),
                date=datetime.now(tz=timezone.utc).date().isoformat(),
            )

        except Exception as exc:
            logger.error("Funnel computation failed", error=str(exc))
            return FunnelResponse(stages=[], conversion_rate=0.0, avg_stages_per_visitor=0.0, date=None)

    def get_occupancy(self) -> OccupancyResponse:
        """Return current zone occupancy from active sessions."""
        db = self._db
        try:
            result = db.execute(
                text("""
                    SELECT
                        z.zone_id,
                        z.name,
                        z.zone_type,
                        z.capacity,
                        COALESCE(s_cnt.cnt, 0) AS current_count
                    FROM zones z
                    LEFT JOIN (
                        SELECT entry_zone, COUNT(*) AS cnt
                        FROM sessions
                        WHERE is_complete = FALSE
                        GROUP BY entry_zone
                    ) s_cnt ON z.zone_id = s_cnt.entry_zone
                    ORDER BY z.zone_id
                """)
            ).fetchall()

            zones = []
            total = 0
            for row in result:
                count = row.current_count or 0
                cap = row.capacity or 1
                util = round(count / cap * 100, 1)
                zones.append(ZoneOccupancy(
                    zone_id=row.zone_id,
                    name=row.name,
                    zone_type=row.zone_type,
                    current_count=count,
                    capacity=cap,
                    utilization_pct=util,
                ))
                total += count

            return OccupancyResponse(
                zones=zones,
                total_in_store=total,
                timestamp=datetime.now(tz=timezone.utc),
            )
        except Exception as exc:
            logger.error("Occupancy query failed", error=str(exc))
            return OccupancyResponse(zones=[], total_in_store=0, timestamp=datetime.now(tz=timezone.utc))

    def get_heatmap(self) -> HeatmapResponse:
        """Generate heatmap data from zone visit counts."""
        db = self._db
        try:
            result = db.execute(
                text("""
                    SELECT
                        z.zone_id,
                        z.name,
                        COUNT(e.id) AS visit_count,
                        AVG(s.duration_seconds) AS avg_dwell
                    FROM zones z
                    LEFT JOIN events e ON e.zone_id = z.zone_id
                        AND e.event_type IN ('zone_enter', 'entry')
                    LEFT JOIN sessions s ON s.entry_zone = z.zone_id
                        AND s.is_complete = TRUE
                    GROUP BY z.zone_id, z.name
                    ORDER BY visit_count DESC
                """)
            ).fetchall()

            max_visits = max((r.visit_count or 0 for r in result), default=1) or 1
            cells = []
            for row in result:
                cx, cy = ZONE_CENTERS.get(row.zone_id, (0.5, 0.5))
                vc = row.visit_count or 0
                cells.append(HeatmapCell(
                    zone_id=row.zone_id,
                    name=row.name,
                    x_center=cx,
                    y_center=cy,
                    visit_count=vc,
                    avg_dwell=round(float(row.avg_dwell or 0), 2),
                    heat_value=round(vc / max_visits, 4),
                ))

            return HeatmapResponse(
                cells=cells,
                max_visits=max_visits,
                date=datetime.now(tz=timezone.utc).date().isoformat(),
            )
        except Exception as exc:
            logger.error("Heatmap query failed", error=str(exc))
            return HeatmapResponse(cells=[], max_visits=0, date=None)
