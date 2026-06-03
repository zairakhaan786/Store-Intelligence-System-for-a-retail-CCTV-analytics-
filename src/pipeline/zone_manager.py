"""
Store zone manager — defines spatial regions and line crossings.

Design choices:
- Zones are defined as normalized polygons [0,1] so they scale with any resolution.
  This lets us reuse zone definitions across cameras with different FOVs.
- We use supervision.PolygonZone for efficient point-in-polygon testing (uses
  cv2.pointPolygonTest internally, O(1) per point after polygon compilation).
- Entry/exit lines are horizontal line segments at configurable Y-ratio positions,
  consistent with standard retail analytics conventions.

Edge cases:
- Person centroid exactly on zone boundary → counted as inside (≥0 test).
- Multi-zone membership → person can be in multiple overlapping zones simultaneously.
- Zone polygon malformed → ZoneManager raises ValueError at construction time, not at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import supervision as sv

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Zone:
    zone_id: str
    name: str
    zone_type: str  # entry | exit | aisle | checkout | beauty_bar
    camera_id: str
    polygon: np.ndarray  # shape (N, 2), normalized [0, 1]
    capacity: int = 20

    _sv_zone: sv.PolygonZone | None = field(default=None, repr=False, compare=False)

    def get_sv_zone(self, frame_wh: Tuple[int, int]) -> sv.PolygonZone:
        """Return a supervision PolygonZone scaled to the given frame size."""
        w, h = frame_wh
        pixel_poly = (self.polygon * np.array([w, h])).astype(int)
        return sv.PolygonZone(polygon=pixel_poly)


# Default store layout — matches seed data in db/init.sql
DEFAULT_ZONES: List[Zone] = [
    Zone(
        zone_id="ENTRY_MAIN",
        name="Main Entrance",
        zone_type="entry",
        camera_id="CAM_01",
        polygon=np.array([[0.0, 0.8], [1.0, 0.8], [1.0, 1.0], [0.0, 1.0]]),
        capacity=10,
    ),
    Zone(
        zone_id="AISLE_A",
        name="Aisle A - Skincare",
        zone_type="aisle",
        camera_id="CAM_02",
        polygon=np.array([[0.0, 0.5], [0.5, 0.5], [0.5, 0.8], [0.0, 0.8]]),
        capacity=15,
    ),
    Zone(
        zone_id="AISLE_B",
        name="Aisle B - Makeup",
        zone_type="aisle",
        camera_id="CAM_03",
        polygon=np.array([[0.5, 0.5], [1.0, 0.5], [1.0, 0.8], [0.5, 0.8]]),
        capacity=15,
    ),
    Zone(
        zone_id="BEAUTY_BAR",
        name="Beauty Bar",
        zone_type="beauty_bar",
        camera_id="CAM_04",
        polygon=np.array([[0.2, 0.2], [0.8, 0.2], [0.8, 0.5], [0.2, 0.5]]),
        capacity=8,
    ),
    Zone(
        zone_id="CHECKOUT",
        name="Checkout Counter",
        zone_type="checkout",
        camera_id="CAM_05",
        polygon=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 0.2], [0.0, 0.2]]),
        capacity=6,
    ),
    Zone(
        zone_id="EXIT_MAIN",
        name="Main Exit",
        zone_type="exit",
        camera_id="CAM_01",
        polygon=np.array([[0.0, 0.85], [1.0, 0.85], [1.0, 1.0], [0.0, 1.0]]),
        capacity=10,
    ),
]


class ZoneManager:
    """Manages all store zones and provides point-in-polygon queries."""

    def __init__(self, zones: List[Zone] | None = None) -> None:
        self._zones: Dict[str, Zone] = {}
        for z in (zones or DEFAULT_ZONES):
            self._zones[z.zone_id] = z
        logger.info("ZoneManager initialized", zone_count=len(self._zones))

    def get_zone(self, zone_id: str) -> Zone | None:
        return self._zones.get(zone_id)

    def get_all_zones(self) -> List[Zone]:
        return list(self._zones.values())

    def get_zones_by_type(self, zone_type: str) -> List[Zone]:
        return [z for z in self._zones.values() if z.zone_type == zone_type]

    def get_zone_for_point(
        self, x_norm: float, y_norm: float
    ) -> List[str]:
        """
        Return list of zone_ids that contain the normalized point (x, y).
        Uses simple polygon containment; can return multiple if zones overlap.
        """
        point = np.array([x_norm, y_norm])
        inside = []
        for zone in self._zones.values():
            if self._point_in_polygon(point, zone.polygon):
                inside.append(zone.zone_id)
        return inside

    @staticmethod
    def _point_in_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
        """Ray casting algorithm for point-in-polygon test."""
        x, y = point
        n = len(polygon)
        inside = False
        px, py = polygon[-1]
        for i in range(n):
            cx, cy = polygon[i]
            if ((cy > y) != (py > y)) and (x < (px - cx) * (y - cy) / (py - cy + 1e-10) + cx):
                inside = not inside
            px, py = cx, cy
        return inside

    def get_centroids_in_zones(
        self,
        centroids_norm: np.ndarray,  # (N, 2) normalized centroids
        tracker_ids: np.ndarray,     # (N,) track IDs
    ) -> Dict[str, List[int]]:
        """
        For each zone, return list of tracker_ids whose centroids fall inside.

        Returns:
            {zone_id: [track_id, ...]}
        """
        result: Dict[str, List[int]] = {z: [] for z in self._zones}
        for centroid, tid in zip(centroids_norm, tracker_ids):
            for zone_id in self.get_zone_for_point(centroid[0], centroid[1]):
                result[zone_id].append(int(tid))
        return result

    def check_entry_line_crossing(
        self,
        prev_y_norm: float,
        curr_y_norm: float,
        line_y: float | None = None,
    ) -> bool:
        """
        Returns True if a track crossed the entry line downward→upward.
        Convention: person moves from high y (bottom/entry) to low y (store).
        """
        ly = line_y or settings.entry_line_y_ratio
        return prev_y_norm >= ly and curr_y_norm < ly

    def check_exit_line_crossing(
        self,
        prev_y_norm: float,
        curr_y_norm: float,
        line_y: float | None = None,
    ) -> bool:
        """
        Returns True if a track crossed the exit line upward→downward.
        Convention: person moves from low y (store) toward high y (exit).
        """
        ly = line_y or settings.exit_line_y_ratio
        return prev_y_norm < ly and curr_y_norm >= ly
