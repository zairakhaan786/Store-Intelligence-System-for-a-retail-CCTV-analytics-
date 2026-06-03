"""
Event Engine — the core business logic layer.

Converts raw tracker outputs into structured business events and persists them to DB.

Event types emitted:
- entry:       person enters the store (crosses entry line)
- exit:        person exits the store
- zone_enter:  person enters a named zone (aisle, checkout, etc.)
- zone_exit:   person leaves a named zone
- dwell:       person has been in a zone beyond dwell threshold (15 mins)
- reentry:     person re-enters after prior exit
- group_entry: ≥3 people enter within 2-second window
- anomaly:     any anomaly detected by AnomalyDetector

Session lifecycle:
1. entry event → create session record (is_complete=False)
2. zone_enter/exit events → append to zones_visited[]
3. exit event → close session (is_complete=True, exit_time set)
4. reentry event → create new session with session_index+1

Design decisions:
- Events are written to DB asynchronously via a queue (in production this would
  be Kafka; here we use a simple list buffer flushed every N frames for simplicity).
- Funnel logic: entry → any aisle → checkout → exit. Conversion = (checkout visits / entries).
- Group entry detection: sliding window over entry timestamps per camera.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import supervision as sv

from src.pipeline.anomaly_detector import AnomalyDetector, AnomalyEvent
from src.pipeline.reentry_handler import ReEntryHandler
from src.pipeline.zone_manager import ZoneManager
from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

DWELL_ALERT_SECONDS = 900  # 15 minutes in zone
GROUP_WINDOW = settings.group_entry_window_seconds
GROUP_MIN_SIZE = settings.group_entry_min_size


@dataclass
class StoreEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    track_id: str = ""
    session_id: Optional[str] = None
    camera_id: str = "CAM_01"
    zone_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    frame_number: int = 0
    confidence: float = 1.0
    bbox: Optional[Dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "track_id": self.track_id,
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "zone_id": self.zone_id,
            "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "frame_number": self.frame_number,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "metadata": self.metadata,
        }


class EventEngine:
    """
    Core event processing engine.
    Consumes tracker outputs per frame and emits structured StoreEvents.
    """

    def __init__(
        self,
        camera_id: str = "CAM_01",
        frame_wh: Tuple[int, int] = (1920, 1080),
        zone_manager: ZoneManager | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._frame_wh = frame_wh
        self._zone_manager = zone_manager or ZoneManager()
        self._reentry = ReEntryHandler()
        self._anomaly = AnomalyDetector()

        # Track state: track_id → {prev_y_norm, zones_in, session_id, enter_time, ...}
        self._track_state: Dict[int, Dict] = {}
        # Session registry: session_id → {entry_time, zones_visited, ...}
        self._sessions: Dict[str, Dict] = {}
        # Active track set (for detecting lost tracks)
        self._active_tracks: set = set()
        # Set of track IDs that have successfully entered to prevent duplicate entry events
        self._all_time_entered_ids: set = set()
        # Entry timestamp buffer for group detection
        self._entry_timestamps: List[float] = []
        # Event buffer (flushed to DB)
        self._event_buffer: List[StoreEvent] = []
        # Frame counter
        self._frame_count = 0

    def process_frame(
        self,
        tracked: sv.Detections,
        frame: np.ndarray,
        timestamp: float | None = None,
    ) -> List[StoreEvent]:
        """
        Process a single frame of tracked detections.

        Args:
            tracked: Detections with tracker_ids populated
            frame: Current video frame (BGR)
            timestamp: Frame timestamp (defaults to now)

        Returns:
            List of StoreEvent objects generated for this frame
        """
        now = timestamp or time.time()
        self._frame_count += 1
        h, w = frame.shape[:2]
        events: List[StoreEvent] = []

        if tracked.tracker_id is None or len(tracked) == 0:
            events.extend(self._handle_lost_tracks(set(), now))
            return events

        current_track_ids = set(tracked.tracker_id.tolist())

        # ── Process each tracked detection ────────────────────────────────
        for i, track_id in enumerate(tracked.tracker_id):
            track_id = int(track_id)
            bbox_xyxy = tracked.xyxy[i]
            confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 1.0

            # Normalize bbox to [0,1]
            x1_n = bbox_xyxy[0] / w
            y1_n = bbox_xyxy[1] / h
            x2_n = bbox_xyxy[2] / w
            y2_n = bbox_xyxy[3] / h
            cx_n = (x1_n + x2_n) / 2
            cy_n = (y1_n + y2_n) / 2

            bbox_norm = (x1_n, y1_n, x2_n, y2_n)
            bbox_dict = {"x1": x1_n, "y1": y1_n, "x2": x2_n, "y2": y2_n}

            is_new_track = track_id not in self._track_state

            if is_new_track:
                self._track_state[track_id] = {
                    "prev_cy_n": cy_n,
                    "zones_in": set(),
                    "session_id": None,
                    "session_index": 0,
                    "enter_time": now,
                    "has_entered": False,
                    "bbox_norm": bbox_norm,
                    "is_reentry": False,
                    "lost_frames": 0,
                }
                logger.info(f"[INFO] Person ID {track_id} track initialized")
            else:
                self._track_state[track_id]["lost_frames"] = 0  # reset lost frames if found

            state = self._track_state[track_id]
            prev_cy_n = state["prev_cy_n"]

            # ── Check for Entry ───────────────────────────────────────────
            if not state["has_entered"]:
                if self._zone_manager.check_entry_line_crossing(prev_cy_n, cy_n):
                    # Check for re-entry
                    reentry_info = self._reentry.check_reentry(
                        track_id, bbox_norm, self._camera_id
                    )
                    session_id = str(uuid.uuid4())
                    session_index = 0
                    is_reentry = False

                    if reentry_info:
                        original_tid, session_index = reentry_info
                        is_reentry = True

                    state["has_entered"] = True
                    state["session_id"] = session_id
                    state["session_index"] = session_index
                    state["is_reentry"] = is_reentry
                    state["enter_time"] = now

                    self._sessions[session_id] = {
                        "track_id": str(track_id),
                        "entry_time": now,
                        "exit_time": None,
                        "zones_visited": [],
                        "session_index": session_index,
                    }

                    ev_type = "reentry" if is_reentry else "entry"
                    
                    # Ensure we only count entry ONCE per track ID, unless it's explicitly a reentry
                    if track_id in self._all_time_entered_ids and not is_reentry:
                        logger.debug(f"[INFO] Prevented duplicate entry for Person ID {track_id}")
                    else:
                        self._all_time_entered_ids.add(track_id)
                        self._entry_timestamps.append(now)
                        self._purge_entry_window(now)

                        entry_event = StoreEvent(
                            event_type=ev_type,
                            track_id=str(track_id),
                            session_id=session_id,
                            camera_id=self._camera_id,
                            zone_id="ENTRY_MAIN",
                            timestamp=now,
                            frame_number=self._frame_count,
                            confidence=confidence,
                            bbox=bbox_dict,
                            metadata={"session_index": session_index, "is_reentry": is_reentry},
                        )
                        events.append(entry_event)
                        self._event_buffer.append(entry_event)
                        logger.info(f"[INFO] Person ID {track_id} entered ({ev_type.upper()} event generated)")

                        # Group entry detection
                        group_events = self._check_group_entry(now, confidence, bbox_dict)
                        events.extend(group_events)
                else:
                    # Prevent duplicate log spam, just debug
                    logger.debug(f"[INFO] Duplicate prevented for Person ID {track_id} before crossing")

            # ── Check for Exit ────────────────────────────────────────────
            elif state["has_entered"]:
                if self._zone_manager.check_exit_line_crossing(prev_cy_n, cy_n):
                    state["has_entered"] = False
                    session_id = state["session_id"]

                    self._reentry.record_exit(
                        track_id=track_id,
                        bbox_norm=bbox_norm,
                        camera_id=self._camera_id,
                        session_index=state.get("session_index", 0),
                    )

                    session = self._sessions.get(session_id, {})
                    duration = now - session.get("entry_time", now)
                    session["exit_time"] = now
                    session["duration_seconds"] = duration

                    exit_event = StoreEvent(
                        event_type="exit",
                        track_id=str(track_id),
                        session_id=session_id,
                        camera_id=self._camera_id,
                        zone_id="EXIT_MAIN",
                        timestamp=now,
                        frame_number=self._frame_count,
                        metadata={
                            "duration_seconds": round(duration, 2),
                            "zones_visited": session.get("zones_visited", []),
                            "session_index": state.get("session_index", 0),
                        },
                    )
                    events.append(exit_event)
                    self._event_buffer.append(exit_event)
                    logger.info(f"[INFO] Person ID {track_id} exited (EXIT event generated)")

            # ── Zone transitions (only if entered) ────────────────────────
            if state["has_entered"]:
                current_zones = set(
                    self._zone_manager.get_zone_for_point(cx_n, cy_n)
                )
                prev_zones = state["zones_in"]

                # Zones entered
                for zone_id in current_zones - prev_zones:
                    zone_enter = StoreEvent(
                        event_type="zone_enter",
                        track_id=str(track_id),
                        session_id=state["session_id"],
                        camera_id=self._camera_id,
                        zone_id=zone_id,
                        timestamp=now,
                        frame_number=self._frame_count,
                        confidence=confidence,
                        bbox=bbox_dict,
                        metadata={"from_zones": list(prev_zones)},
                    )
                    events.append(zone_enter)
                    self._event_buffer.append(zone_enter)
                    self._anomaly.track_entered_zone(str(track_id), zone_id, now)
                    session = self._sessions.get(state["session_id"], {})
                    if zone_id not in session.get("zones_visited", []):
                        session.setdefault("zones_visited", []).append(zone_id)

                # Zones exited
                for zone_id in prev_zones - current_zones:
                    zone_exit = StoreEvent(
                        event_type="zone_exit",
                        track_id=str(track_id),
                        session_id=state["session_id"],
                        camera_id=self._camera_id,
                        zone_id=zone_id,
                        timestamp=now,
                        frame_number=self._frame_count,
                        confidence=confidence,
                        bbox=bbox_dict,
                    )
                    events.append(zone_exit)
                    self._event_buffer.append(zone_exit)
                    self._anomaly.track_exited_zone(str(track_id), zone_id)

                # Anomaly checks
                for zone_id in current_zones:
                    zone = self._zone_manager.get_zone(zone_id)
                    if zone:
                        dwell_anoms = self._anomaly.check_dwell_anomalies(
                            zone_id, [str(track_id)], now
                        )
                        for anom in dwell_anoms:
                            anom_event = self._anomaly_to_event(anom, confidence, bbox_dict)
                            events.append(anom_event)
                            self._event_buffer.append(anom_event)

                state["zones_in"] = current_zones

            # ── Update state ──────────────────────────────────────────────
            state["prev_cy_n"] = cy_n
            state["bbox_norm"] = bbox_norm

        # ── Handle lost tracks (people who left frame) ─────────────────────
        lost_events = self._handle_lost_tracks(current_track_ids, now)
        events.extend(lost_events)

        return events

    def _handle_lost_tracks(
        self,
        current_track_ids: set,
        now: float,
    ) -> List[StoreEvent]:
        """Emit exit events for tracks that are no longer visible after max_age."""
        events = []
        lost = set(self._track_state.keys()) - current_track_ids

        for track_id in lost:
            state = self._track_state[track_id]
            state["lost_frames"] = state.get("lost_frames", 0) + 1

            if state["lost_frames"] <= settings.tracker_max_age:
                continue  # Keep state, don't exit yet

            # Max age reached, retire the track
            self._track_state.pop(track_id)
            self._active_tracks.discard(track_id)

            if not state.get("has_entered", False):
                logger.info(f"[INFO] Person ID {track_id} track dropped before entry")
                continue

            # Record exit for re-entry detection
            self._reentry.record_exit(
                track_id=track_id,
                bbox_norm=state.get("bbox_norm", (0, 0, 0, 0)),
                camera_id=self._camera_id,
                session_index=state.get("session_index", 0),
            )

            # Close session
            session_id = state["session_id"]
            session = self._sessions.get(session_id, {})
            duration = now - session.get("entry_time", now)
            session["exit_time"] = now
            session["duration_seconds"] = duration

            exit_event = StoreEvent(
                event_type="exit",
                track_id=str(track_id),
                session_id=session_id,
                camera_id=self._camera_id,
                zone_id="EXIT_MAIN",
                timestamp=now,
                frame_number=self._frame_count,
                metadata={
                    "duration_seconds": round(duration, 2),
                    "zones_visited": session.get("zones_visited", []),
                    "session_index": state.get("session_index", 0),
                },
            )
            events.append(exit_event)
            self._event_buffer.append(exit_event)
            logger.info(f"[INFO] Person ID {track_id} exited (track lost for {state['lost_frames']} frames, EXIT event generated)")

        return events

    def _check_group_entry(
        self, now: float, confidence: float, bbox_dict: Dict
    ) -> List[StoreEvent]:
        """Detect group entry: ≥ GROUP_MIN_SIZE entries within GROUP_WINDOW seconds."""
        recent = [t for t in self._entry_timestamps if now - t <= GROUP_WINDOW]
        if len(recent) >= GROUP_MIN_SIZE:
            ev = StoreEvent(
                event_type="group_entry",
                track_id="GROUP",
                camera_id=self._camera_id,
                zone_id="ENTRY_MAIN",
                timestamp=now,
                frame_number=self._frame_count,
                confidence=confidence,
                bbox=bbox_dict,
                metadata={"group_size": len(recent), "window_seconds": GROUP_WINDOW},
            )
            # Clear buffer to avoid re-triggering immediately
            self._entry_timestamps.clear()
            logger.info("Group entry detected", size=len(recent))
            return [ev]
        return []

    def _purge_entry_window(self, now: float) -> None:
        self._entry_timestamps = [
            t for t in self._entry_timestamps if now - t <= GROUP_WINDOW
        ]

    def _anomaly_to_event(
        self, anom: AnomalyEvent, confidence: float, bbox_dict: Dict
    ) -> StoreEvent:
        return StoreEvent(
            event_type="anomaly",
            track_id=anom.track_id or "",
            camera_id=self._camera_id,
            zone_id=anom.zone_id,
            timestamp=anom.detected_at,
            frame_number=self._frame_count,
            confidence=confidence,
            bbox=bbox_dict,
            metadata={
                "anomaly_type": anom.anomaly_type,
                "severity": anom.severity,
                "description": anom.description,
                **anom.metadata,
            },
        )

    def flush_buffer(self) -> List[StoreEvent]:
        """Return and clear the event buffer."""
        buf = list(self._event_buffer)
        self._event_buffer.clear()
        return buf

    def get_current_occupancy(self) -> Dict[str, int]:
        """Return {zone_id: count} of current active tracks per zone."""
        occupancy: Dict[str, int] = defaultdict(int)
        for state in self._track_state.values():
            for zone_id in state.get("zones_in", set()):
                occupancy[zone_id] += 1
        return dict(occupancy)

    @property
    def total_entries(self) -> int:
        return sum(
            1 for e in self._event_buffer if e.event_type in ("entry", "reentry")
        )
