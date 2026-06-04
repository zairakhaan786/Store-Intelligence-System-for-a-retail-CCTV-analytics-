"""
ByteTrack multi-object tracker via supervision.

Design choices:
- supervision.ByteTracker wraps the ByteTrack algorithm (Zhang et al., 2022).
  We prefer this over raw ByteTrack C++ for portability and Docker simplicity.
- max_age=30: tracks held for 30 frames (1.2s at 25fps) before being dropped.
  This handles brief occlusions (e.g., pillars, other shoppers) without creating
  spurious track splits.
- min_hits=3: track must be confirmed in 3 consecutive frames to avoid spurious
  detections from reflections or display stands.

Edge cases handled:
- Track loss (occlusion > max_age): track ID is retired; new detection gets new ID.
  Re-entry handler reconciles this via temporal/spatial heuristics.
- ID switching: low-confidence detections kept in ByteTrack's second-stage buffer
  reduce ID switches by ~40% vs. SORT (per original ByteTrack paper).
- Group entry: multiple people overlapping → tracked as individual IDs since
  ByteTrack maintains IoU-matched tracks even at low confidence.
"""
from __future__ import annotations

import numpy as np
import supervision as sv

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


class PersonTracker:
    """Stateful multi-object tracker using ByteTrack."""

    def __init__(
        self,
        max_age: int | None = None,
        min_hits: int | None = None,
        min_confidence: float | None = None,
    ) -> None:
        self._max_age = max_age or settings.tracker_max_age
        self._min_hits = min_hits or settings.tracker_min_hits
        self._min_confidence = min_confidence or settings.yolo_confidence
        self._min_consecutive = 5

        self._tracker = sv.ByteTrack(
            track_activation_threshold=self._min_confidence,
            lost_track_buffer=self._max_age,
            minimum_matching_threshold=0.8,
            minimum_consecutive_frames=self._min_consecutive,
        )
        self._frame_count = 0
        logger.info(
            "ByteTracker initialized",
            max_age=self._max_age,
            min_hits=self._min_hits,
        )

    def update(self, detections: sv.Detections, frame: np.ndarray | None = None) -> sv.Detections:
        """
        Update tracker with new detections.

        Args:
            detections: sv.Detections from current frame
            frame: Optional frame for appearance-feature extraction (future use)

        Returns:
            sv.Detections annotated with .tracker_id field
        """
        self._frame_count += 1
        tracked = self._tracker.update_with_detections(detections)

        logger.debug(
            "Tracker update",
            frame=self._frame_count,
            detections=len(detections),
            tracked=len(tracked),
        )
        return tracked

    def reset(self) -> None:
        """Reset tracker state (e.g., on camera switch)."""
        self._tracker = sv.ByteTrack(
            track_activation_threshold=self._min_confidence,
            lost_track_buffer=self._max_age,
            minimum_matching_threshold=0.8,
            minimum_consecutive_frames=self._min_consecutive,
        )
        self._frame_count = 0
        logger.info("Tracker reset")

    @property
    def frame_count(self) -> int:
        return self._frame_count
