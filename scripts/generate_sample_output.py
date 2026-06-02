"""
Sample output generator — creates screenshots and sample API responses
for README documentation.

Run: python scripts/generate_sample_output.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("docs/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def generate_sample_metrics() -> dict:
    return {
        "total_entries": 127,
        "total_exits": 118,
        "unique_visitors": 112,
        "avg_dwell_seconds": 847.3,
        "peak_occupancy": 23,
        "conversion_rate": 0.417,
        "reentry_count": 15,
        "group_entry_count": 8,
        "active_sessions": 9,
        "anomaly_count": 2,
        "staff_count": 3,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def generate_sample_events() -> list:
    return [
        {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "event_type": "entry",
            "track_id": "TRACK_42",
            "session_id": "f1e2d3c4-b5a6-7890-abcd-123456789abc",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": "2026-06-01T09:32:14Z",
            "frame_number": 423,
            "confidence": 0.89,
            "bbox": {"x1": 0.31, "y1": 0.72, "x2": 0.48, "y2": 0.99},
            "metadata": {"session_index": 0, "is_reentry": False},
        },
        {
            "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "event_type": "reentry",
            "track_id": "TRACK_17",
            "session_id": "e2d3c4b5-a6f7-8901-bcde-234567890123",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": "2026-06-01T09:47:22Z",
            "frame_number": 1147,
            "confidence": 0.84,
            "bbox": {"x1": 0.21, "y1": 0.75, "x2": 0.39, "y2": 0.99},
            "metadata": {"session_index": 1, "is_reentry": True},
        },
        {
            "id": "c3d4e5f6-a7b8-9012-cdef-234567890123",
            "event_type": "group_entry",
            "track_id": "GROUP",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": "2026-06-01T11:15:09Z",
            "frame_number": 6231,
            "confidence": 1.0,
            "bbox": {"x1": 0.1, "y1": 0.7, "x2": 0.9, "y2": 0.99},
            "metadata": {"group_size": 4, "window_seconds": 2},
        },
        {
            "id": "d4e5f6a7-b8c9-0123-defa-345678901234",
            "event_type": "anomaly",
            "track_id": "TRACK_9",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": "2026-06-01T14:22:51Z",
            "frame_number": 32141,
            "confidence": 0.91,
            "bbox": {"x1": 0.40, "y1": 0.78, "x2": 0.57, "y2": 0.99},
            "metadata": {
                "anomaly_type": "loitering",
                "severity": "medium",
                "dwell_seconds": 147.3,
                "description": "TRACK_9 loitering in ENTRY_MAIN for 147s",
            },
        },
    ]


def generate_sample_funnel() -> dict:
    return {
        "stages": [
            {"stage": "Entry", "count": 127, "pct_from_entry": 100.0},
            {"stage": "Aisle Browse", "count": 98, "pct_from_entry": 77.2},
            {"stage": "Beauty Bar", "count": 61, "pct_from_entry": 48.0},
            {"stage": "Checkout", "count": 53, "pct_from_entry": 41.7},
            {"stage": "Exit", "count": 118, "pct_from_entry": 92.9},
        ],
        "conversion_rate": 0.417,
        "avg_stages_per_visitor": 3.2,
        "date": "2026-06-01",
    }


def generate_sample_anomalies() -> dict:
    return {
        "anomalies": [
            {
                "id": "a1111111-2222-3333-4444-555555555555",
                "anomaly_type": "loitering",
                "severity": "medium",
                "zone_id": "ENTRY_MAIN",
                "track_id": "TRACK_9",
                "description": "TRACK_9 loitering in ENTRY_MAIN for 147s (>120s threshold)",
                "detected_at": "2026-06-01T14:22:51Z",
                "is_active": True,
            },
            {
                "id": "b2222222-3333-4444-5555-666666666666",
                "anomaly_type": "overcrowding",
                "severity": "high",
                "zone_id": "BEAUTY_BAR",
                "track_id": None,
                "description": "Zone BEAUTY_BAR has 8/8 people for >60s",
                "detected_at": "2026-06-01T15:45:33Z",
                "is_active": False,
            },
        ],
        "total": 2,
        "active_count": 1,
    }


def save_outputs():
    samples = {
        "sample_metrics.json": generate_sample_metrics(),
        "sample_events.json": {"events": generate_sample_events(), "total": 4, "page": 1, "page_size": 50},
        "sample_funnel.json": generate_sample_funnel(),
        "sample_anomalies.json": generate_sample_anomalies(),
    }

    for filename, data in samples.items():
        path = OUTPUT_DIR / filename
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"✓ Generated {path}")

    print(f"\n✅ Sample outputs written to {OUTPUT_DIR}/")
    print("Use these in README.md for API documentation examples.")


if __name__ == "__main__":
    save_outputs()
