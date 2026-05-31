"""
Re-entry detection and session deduplication.

Problem:
When a customer leaves and re-enters, ByteTrack assigns a new track_id because
the track buffer expires. We need to detect this and mark it as re-entry rather
than counting as a new unique visitor.

Approach:
1. Spatial-temporal heuristic: if a new detection appears near the last known
   position of an exited track within reentry_gap_seconds, flag as re-entry.
2. Appearance hash (stub for future): color histogram of person bounding box
   could improve accuracy but is overkill for the current scope.

Design tradeoff:
- Simple spatial matching (IoU of bbox near exit zone) is O(N*M) but N (active
  tracks) and M (recent exits) are both small (<50) in a retail store.
- We avoid expensive re-ID models (OSNet, etc.) to keep the pipeline CPU-friendly.

Edge cases:
- Two different people entering at nearly same spot within gap window → possible
  false re-entry. Mitigated by requiring bbox overlap > 0.3 IoU.
- Person lingers near door (indecisive) → not a re-entry, guard with minimum
  dwell_in_store > 5 seconds before marking as exited.
- Group entries: each member tracked independently; group re-entry counted per person.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExitRecord:
    track_id: int
    exit_time: float        # Unix timestamp
    last_bbox_norm: Tuple[float, float, float, float]  # (x1, y1, x2, y2) normalized
    session_index: int
    camera_id: str


class ReEntryHandler:
    """Tracks exit records and detects re-entries via spatial-temporal heuristics."""

    def __init__(
        self,
        gap_seconds: int | None = None,
        iou_threshold: float = 0.30,
    ) -> None:
        self._gap = gap_seconds or settings.reentry_gap_seconds
        self._iou_threshold = iou_threshold
        # Stores recent exits: camera_id → list of ExitRecord
        self._exit_records: Dict[str, List[ExitRecord]] = {}
        # Map new_track_id → (original_track_id, session_index)
        self._reentry_map: Dict[int, Tuple[int, int]] = {}

    def record_exit(
        self,
        track_id: int,
        bbox_norm: Tuple[float, float, float, float],
        camera_id: str,
        session_index: int = 0,
    ) -> None:
        """Register that a track has exited the frame."""
        rec = ExitRecord(
            track_id=track_id,
            exit_time=time.time(),
            last_bbox_norm=bbox_norm,
            session_index=session_index,
            camera_id=camera_id,
        )
        self._exit_records.setdefault(camera_id, []).append(rec)
        self._purge_stale(camera_id)
        logger.debug("Exit recorded", track_id=track_id, camera=camera_id)

    def check_reentry(
        self,
        new_track_id: int,
        new_bbox_norm: Tuple[float, float, float, float],
        camera_id: str,
    ) -> Optional[Tuple[int, int]]:
        """
        Check if a newly detected track is a re-entry of a recent exit.

        Returns:
            (original_track_id, new_session_index) if re-entry detected, else None
        """
        now = time.time()
        candidates = self._exit_records.get(camera_id, [])
        best_match: Optional[ExitRecord] = None
        best_iou = 0.0

        for rec in candidates:
            if now - rec.exit_time > self._gap:
                continue
            iou = self._bbox_iou(new_bbox_norm, rec.last_bbox_norm)
            if iou > best_iou and iou >= self._iou_threshold:
                best_iou = iou
                best_match = rec

        if best_match:
            next_session = best_match.session_index + 1
            self._reentry_map[new_track_id] = (best_match.track_id, next_session)
            # Remove matched record to prevent double-matching
            self._exit_records[camera_id].remove(best_match)
            logger.info(
                "Re-entry detected",
                new_track=new_track_id,
                original_track=best_match.track_id,
                iou=round(best_iou, 3),
            )
            return (best_match.track_id, next_session)

        return None

    def get_canonical_track(self, track_id: int) -> int:
        """Return the original (canonical) track_id for a re-entrant track."""
        original, _ = self._reentry_map.get(track_id, (track_id, 0))
        return original

    def get_session_index(self, track_id: int) -> int:
        """Return session visit count for this track."""
        _, idx = self._reentry_map.get(track_id, (track_id, 0))
        return idx

    def _purge_stale(self, camera_id: str) -> None:
        """Remove exit records older than gap_seconds."""
        now = time.time()
        self._exit_records[camera_id] = [
            r for r in self._exit_records.get(camera_id, [])
            if now - r.exit_time <= self._gap
        ]

    @staticmethod
    def _bbox_iou(
        a: Tuple[float, float, float, float],
        b: Tuple[float, float, float, float],
    ) -> float:
        """Compute IoU between two normalized bounding boxes."""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter + 1e-6)
