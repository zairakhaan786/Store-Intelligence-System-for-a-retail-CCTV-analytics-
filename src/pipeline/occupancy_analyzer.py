"""
Aerial/Top-View Occupancy Analyzer.

For top-down CCTV cameras (common in retail stores for full-aisle coverage),
we compute density maps using a grid-based approach rather than polygon zones.

Design decisions:
- Grid-based density vs. polygon zones:
  Grid gives continuous spatial distribution; zones give categorical
  We use both: zones for business logic, grid for heatmap visualization

- Density estimation method:
  Gaussian kernel around each detected centroid (σ = 0.05 of frame width)
  This avoids hard "1 person = 1 cell" counting that creates blocky heatmaps

- Occupancy calculation:
  Real occupancy = count of tracked people in zone
  Estimated density = Gaussian blur of presence mask
  Both are computed and reported separately

Edge cases:
- Very dense crowds (people overlap in bounding boxes):
  We use detection centroids + kernel, not bounding box area
  → More accurate for high-density zones

- Top-down vs. side-view cameras:
  This analyzer is optimized for top-down (aerial) views
  Side-view: use the standard ZoneManager with line crossings
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from src.shared.logger import get_logger

logger = get_logger(__name__)

# Grid resolution for density map
GRID_COLS = 20
GRID_ROWS = 20
# Gaussian kernel sigma (as fraction of frame dimension)
SIGMA_FRACTION = 0.04


@dataclass
class OccupancyResult:
    grid: np.ndarray                      # (rows, cols) density values [0,1]
    zone_counts: Dict[str, int]           # zone_id → person count
    peak_cell: Tuple[int, int]            # (row, col) of highest density
    peak_density: float                   # max density value
    total_count: int                      # total people in frame
    congestion_zones: List[str]           # zones > 80% density


class OccupancyAnalyzer:
    """
    Computes zone occupancy and density maps from tracked person centroids.
    Works for both aerial and side-view cameras.
    """

    def __init__(self, grid_rows: int = GRID_ROWS, grid_cols: int = GRID_COLS) -> None:
        self._rows = grid_rows
        self._cols = grid_cols
        self._history: List[np.ndarray] = []  # rolling density history (last 30 frames)
        self._max_history = 30
        logger.info("OccupancyAnalyzer initialized", grid=f"{grid_rows}×{grid_cols}")

    def compute(
        self,
        centroids_norm: np.ndarray,        # (N, 2) normalized [0,1] centroids
        zone_polygons: Dict[str, np.ndarray],  # zone_id → polygon [[x,y]...]
        capacity_map: Dict[str, int],          # zone_id → max capacity
    ) -> OccupancyResult:
        """
        Compute occupancy grid and zone-level counts.

        Args:
            centroids_norm: Array of normalized person centroids
            zone_polygons: Store zone polygon definitions
            capacity_map: Maximum capacity per zone

        Returns:
            OccupancyResult with density grid and zone counts
        """
        n_people = len(centroids_norm)
        density_grid = np.zeros((self._rows, self._cols), dtype=np.float32)

        if n_people == 0:
            return OccupancyResult(
                grid=density_grid,
                zone_counts={zid: 0 for zid in zone_polygons},
                peak_cell=(0, 0),
                peak_density=0.0,
                total_count=0,
                congestion_zones=[],
            )

        # ── Build density grid using Gaussian kernels ─────────────────────
        sigma_r = SIGMA_FRACTION * self._rows
        sigma_c = SIGMA_FRACTION * self._cols

        for cx, cy in centroids_norm:
            # Convert normalized coords to grid indices
            gc = min(int(cx * self._cols), self._cols - 1)
            gr = min(int(cy * self._rows), self._rows - 1)

            # Add Gaussian kernel centered at this person
            for r in range(self._rows):
                for c in range(self._cols):
                    dist_r = (r - gr) / sigma_r
                    dist_c = (c - gc) / sigma_c
                    density_grid[r, c] += np.exp(-0.5 * (dist_r**2 + dist_c**2))

        # Normalize to [0, 1]
        if density_grid.max() > 0:
            density_grid /= density_grid.max()

        # ── Update rolling history for temporal smoothing ─────────────────
        self._history.append(density_grid.copy())
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Temporal smoothed grid (EMA)
        if len(self._history) > 1:
            weights = np.exp(np.linspace(-1, 0, len(self._history)))
            weights /= weights.sum()
            smoothed = sum(w * g for w, g in zip(weights, self._history))
        else:
            smoothed = density_grid

        # ── Zone-level counting (exact centroid containment) ──────────────
        zone_counts: Dict[str, int] = {}
        for zone_id, polygon in zone_polygons.items():
            count = sum(
                1 for cx, cy in centroids_norm
                if self._point_in_poly(cx, cy, polygon)
            )
            zone_counts[zone_id] = count

        # ── Find peak density cell ────────────────────────────────────────
        peak_idx = np.unravel_index(np.argmax(smoothed), smoothed.shape)
        peak_density = float(smoothed[peak_idx])

        # ── Identify congested zones (count > 80% of capacity) ───────────
        congestion_zones = [
            zid for zid, count in zone_counts.items()
            if count >= 0.8 * capacity_map.get(zid, 20)
        ]

        return OccupancyResult(
            grid=smoothed.astype(np.float32),
            zone_counts=zone_counts,
            peak_cell=(int(peak_idx[0]), int(peak_idx[1])),
            peak_density=peak_density,
            total_count=n_people,
            congestion_zones=congestion_zones,
        )

    def get_heatmap_image(
        self,
        result: OccupancyResult,
        width: int = 640,
        height: int = 480,
        colormap: int = None,
    ) -> np.ndarray:
        """
        Convert density grid to a color heatmap image.

        Returns:
            BGR numpy array of size (height, width, 3)
        """
        import cv2
        colormap = colormap or cv2.COLORMAP_JET
        grid_uint8 = (result.grid * 255).astype(np.uint8)
        resized = cv2.resize(grid_uint8, (width, height), interpolation=cv2.INTER_LINEAR)
        heatmap_color = cv2.applyColorMap(resized, colormap)
        return heatmap_color

    def get_smoothed_grid(self) -> np.ndarray:
        """Return the temporally smoothed density grid."""
        if not self._history:
            return np.zeros((self._rows, self._cols), dtype=np.float32)
        return self._history[-1]

    @staticmethod
    def _point_in_poly(x: float, y: float, polygon: np.ndarray) -> bool:
        """Ray casting for point-in-polygon test."""
        n = len(polygon)
        inside = False
        px, py = polygon[-1]
        for i in range(n):
            cx, cy = polygon[i]
            if ((cy > y) != (py > y)) and (x < (px - cx) * (y - cy) / (py - cy + 1e-10) + cx):
                inside = not inside
            px, py = cx, cy
        return inside
