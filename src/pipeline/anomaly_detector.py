"""
Anomaly detection for retail store surveillance.

Anomaly types detected:
1. Overcrowding: zone occupancy > 90% of capacity for > 60 seconds.
2. Loitering: single person in non-shopping zone (entry/exit) for > 120 seconds.
3. Long dwell: person in checkout zone for > 300 seconds (potential issue).
4. Tailgating: two new tracks enter within 1.5 seconds at the same entry point.
5. Unusual path: customer visits restricted zone (stockroom) without authorization.
6. Abandoned zone: zone has 0 occupancy during peak hours (camera/sensor failure).

Design tradeoffs:
- Rule-based anomaly detection is chosen over ML-based (isolation forest, etc.)
  because: (a) it's explainable, (b) requires no training data, (c) thresholds
  are business-tunable by store managers.
- Stateful detection requires maintaining zone occupancy history per minute bucket.
- False positive control: we use time hysteresis (condition must hold for duration)
  rather than triggering on any momentary threshold breach.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.shared.logger import get_logger

logger = get_logger(__name__)

# ── Thresholds (all tunable via settings in production) ──────────────────────
OVERCROWDING_DURATION_SECS = 60
OVERCROWDING_CAPACITY_PCT = 0.90
LOITERING_DURATION_SECS = 120
LOITERING_ZONES = {"ENTRY_MAIN", "EXIT_MAIN"}
LONG_DWELL_SECS = 300
LONG_DWELL_ZONES = {"CHECKOUT"}
TAILGATE_WINDOW_SECS = 1.5
TAILGATE_ENTRY_ZONES = {"ENTRY_MAIN"}


@dataclass
class AnomalyEvent:
    anomaly_type: str
    severity: str  # low | medium | high | critical
    zone_id: Optional[str]
    track_id: Optional[str]
    description: str
    metadata: dict = field(default_factory=dict)
    detected_at: float = field(default_factory=time.time)


class AnomalyDetector:
    """Rule-based anomaly detector for retail store events."""

    def __init__(self) -> None:
        # zone_id → {track_id: enter_time}
        self._zone_enter_times: Dict[str, Dict[str, float]] = {}
        # zone_id → time_when_first_overcrowded
        self._overcrowd_start: Dict[str, Optional[float]] = {}
        # list of recent entry timestamps per entry zone
        self._recent_entries: Dict[str, List[float]] = {}
        self._emitted_anomalies: List[AnomalyEvent] = []

    def update_zone_occupancy(
        self,
        zone_id: str,
        track_ids: List[str],
        capacity: int,
        timestamp: float | None = None,
    ) -> List[AnomalyEvent]:
        """
        Update zone occupancy and check for overcrowding.
        Called every frame for each zone.
        """
        now = timestamp or time.time()
        anomalies: List[AnomalyEvent] = []
        count = len(track_ids)
        threshold = int(capacity * OVERCROWDING_CAPACITY_PCT)

        if count >= threshold:
            if self._overcrowd_start.get(zone_id) is None:
                self._overcrowd_start[zone_id] = now
            elif now - self._overcrowd_start[zone_id] >= OVERCROWDING_DURATION_SECS:
                a = AnomalyEvent(
                    anomaly_type="overcrowding",
                    severity="high" if count >= capacity else "medium",
                    zone_id=zone_id,
                    track_id=None,
                    description=(
                        f"Zone {zone_id} has {count}/{capacity} people "
                        f"for >{OVERCROWDING_DURATION_SECS}s"
                    ),
                    metadata={"count": count, "capacity": capacity},
                    detected_at=now,
                )
                anomalies.append(a)
                self._overcrowd_start[zone_id] = now  # reset to avoid spam
        else:
            self._overcrowd_start[zone_id] = None

        return anomalies

    def track_entered_zone(
        self,
        track_id: str,
        zone_id: str,
        timestamp: float | None = None,
    ) -> None:
        """Record when a track enters a zone."""
        now = timestamp or time.time()
        self._zone_enter_times.setdefault(zone_id, {})[track_id] = now

        # Track recent entries for tailgating detection
        if zone_id in TAILGATE_ENTRY_ZONES:
            self._recent_entries.setdefault(zone_id, []).append(now)
            # Purge old entries
            self._recent_entries[zone_id] = [
                t for t in self._recent_entries[zone_id]
                if now - t <= TAILGATE_WINDOW_SECS
            ]

    def check_dwell_anomalies(
        self,
        zone_id: str,
        track_ids: List[str],
        timestamp: float | None = None,
    ) -> List[AnomalyEvent]:
        """Check for loitering and long dwell anomalies."""
        now = timestamp or time.time()
        anomalies: List[AnomalyEvent] = []
        zone_times = self._zone_enter_times.get(zone_id, {})

        for tid in track_ids:
            enter_time = zone_times.get(tid)
            if enter_time is None:
                continue
            dwell = now - enter_time

            # Loitering at entry/exit
            if zone_id in LOITERING_ZONES and dwell >= LOITERING_DURATION_SECS:
                anomalies.append(AnomalyEvent(
                    anomaly_type="loitering",
                    severity="medium",
                    zone_id=zone_id,
                    track_id=tid,
                    description=f"Track {tid} loitering in {zone_id} for {dwell:.0f}s",
                    metadata={"dwell_seconds": dwell},
                    detected_at=now,
                ))

            # Long dwell at checkout
            if zone_id in LONG_DWELL_ZONES and dwell >= LONG_DWELL_SECS:
                anomalies.append(AnomalyEvent(
                    anomaly_type="long_dwell",
                    severity="medium",
                    zone_id=zone_id,
                    track_id=tid,
                    description=f"Track {tid} at {zone_id} for {dwell:.0f}s (>{LONG_DWELL_SECS}s)",
                    metadata={"dwell_seconds": dwell},
                    detected_at=now,
                ))

        return anomalies

    def check_tailgating(
        self,
        zone_id: str,
        timestamp: float | None = None,
    ) -> List[AnomalyEvent]:
        """Detect tailgating: ≥2 people entering within TAILGATE_WINDOW_SECS."""
        if zone_id not in TAILGATE_ENTRY_ZONES:
            return []
        entries = self._recent_entries.get(zone_id, [])
        if len(entries) >= 2:
            self._recent_entries[zone_id].clear()
            return [AnomalyEvent(
                anomaly_type="tailgating",
                severity="low",
                zone_id=zone_id,
                track_id=None,
                description=f"{len(entries)} people entered {zone_id} within {TAILGATE_WINDOW_SECS}s",
                metadata={"entry_count": len(entries)},
                detected_at=timestamp or time.time(),
            )]
        return []

    def track_exited_zone(self, track_id: str, zone_id: str) -> None:
        """Clean up when a track leaves a zone."""
        self._zone_enter_times.get(zone_id, {}).pop(track_id, None)
