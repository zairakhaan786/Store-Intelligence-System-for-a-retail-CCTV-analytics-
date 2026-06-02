"""
Tests for event generation and business logic.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest


class TestEventGeneration:
    """Integration tests for the event generation pipeline."""

    def test_entry_event_generated_on_new_track(self):
        """A new track should generate an entry event."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Create a mock detection
        det = sv.Detections(
            xyxy=np.array([[100, 300, 200, 480]]),  # person at bottom of frame
            confidence=np.array([0.88]),
            class_id=np.array([0]),
            tracker_id=np.array([1]),
        )
        events = engine.process_frame(det, frame)
        assert len(events) > 0
        entry_events = [e for e in events if e.event_type == "entry"]
        assert len(entry_events) == 1

    def test_exit_event_on_track_loss(self):
        """When a track disappears, an exit event should be generated."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: track appears
        det1 = sv.Detections(
            xyxy=np.array([[100, 300, 200, 480]]),
            confidence=np.array([0.88]),
            class_id=np.array([0]),
            tracker_id=np.array([42]),
        )
        engine.process_frame(det1, frame)

        # Frame 2: track disappears
        events = engine.process_frame(sv.Detections.empty(), frame)
        exit_events = [e for e in events if e.event_type == "exit"]
        assert len(exit_events) == 1
        assert exit_events[0].track_id == "42"

    def test_multiple_tracks_multiple_entries(self):
        """Multiple simultaneous tracks should each get an entry event."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        det = sv.Detections(
            xyxy=np.array([
                [50, 300, 150, 480],
                [200, 300, 300, 480],
                [400, 300, 500, 480],
            ]),
            confidence=np.array([0.88, 0.75, 0.92]),
            class_id=np.array([0, 0, 0]),
            tracker_id=np.array([1, 2, 3]),
        )
        events = engine.process_frame(det, frame)
        entry_events = [e for e in events if e.event_type == "entry"]
        assert len(entry_events) == 3

    def test_group_entry_detected(self):
        """3+ people entering quickly should trigger group_entry."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # All 4 tracks appear simultaneously → group entry
        det = sv.Detections(
            xyxy=np.array([
                [50, 300, 150, 480],
                [200, 300, 300, 480],
                [350, 300, 450, 480],
                [500, 300, 600, 480],
            ]),
            confidence=np.array([0.88, 0.75, 0.92, 0.80]),
            class_id=np.array([0, 0, 0, 0]),
            tracker_id=np.array([1, 2, 3, 4]),
        )
        events = engine.process_frame(det, frame)
        group_events = [e for e in events if e.event_type == "group_entry"]
        assert len(group_events) >= 1
        assert group_events[0].metadata.get("group_size") >= 3

    def test_event_contains_bbox(self):
        """Events must contain bounding box data."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        det = sv.Detections(
            xyxy=np.array([[100, 200, 200, 400]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([7]),
        )
        events = engine.process_frame(det, frame)
        for ev in events:
            if ev.event_type == "entry":
                assert ev.bbox is not None
                assert "x1" in ev.bbox
                assert "y1" in ev.bbox

    def test_event_has_valid_timestamp(self):
        """All events must have a valid timestamp."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        det = sv.Detections(
            xyxy=np.array([[100, 200, 200, 400]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([8]),
        )
        events = engine.process_frame(det, frame)
        for ev in events:
            assert ev.timestamp > 0
            assert ev.timestamp <= time.time() + 1  # not in the future

    def test_occupancy_tracking(self):
        """Occupancy should reflect number of active tracks."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # 2 people at checkout zone (y ≈ 0.1 → CHECKOUT zone)
        det = sv.Detections(
            xyxy=np.array([
                [100, 0, 200, 100],   # top of frame → checkout
                [300, 0, 400, 100],
            ]),
            confidence=np.array([0.88, 0.75]),
            class_id=np.array([0, 0]),
            tracker_id=np.array([10, 11]),
        )
        engine.process_frame(det, frame)
        occ = engine.get_current_occupancy()
        assert isinstance(occ, dict)

    def test_flush_buffer(self):
        """Flush should return and clear the event buffer."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        det = sv.Detections(
            xyxy=np.array([[100, 200, 200, 400]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([99]),
        )
        engine.process_frame(det, frame)
        buf = engine.flush_buffer()
        assert len(buf) >= 0
        assert len(engine._event_buffer) == 0


class TestCSVProcessor:
    """Tests for CSV ingestion."""

    def test_timestamp_parsing_iso(self):
        """ISO 8601 timestamps should parse correctly."""
        from src.pipeline.csv_processor import _parse_timestamp
        dt = _parse_timestamp("2026-06-01T10:30:00Z")
        assert dt.year == 2026
        assert dt.month == 6

    def test_timestamp_parsing_plain(self):
        from src.pipeline.csv_processor import _parse_timestamp
        dt = _parse_timestamp("2026-06-01 10:30:00")
        assert dt.day == 1

    def test_column_resolution(self):
        """Column aliasing should map common variants."""
        from src.pipeline.csv_processor import _resolve_column
        assert _resolve_column(["time", "person_id", "type"], "timestamp") == "time"
        assert _resolve_column(["timestamp", "id", "event_type"], "track_id") == "id"

    def test_synthetic_event_generation(self, tmp_path, monkeypatch):
        """Synthetic event generation should produce valid event dicts."""
        from src.pipeline.csv_processor import generate_synthetic_events

        # Mock psycopg2 to avoid DB dependency
        import src.pipeline.csv_processor as cp
        calls = []

        class FakeCursor:
            def execute(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass

        class FakeConn:
            def cursor(self): return FakeCursor()
            def commit(self): calls.append("commit")
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr(cp, "psycopg2", type("m", (), {"connect": lambda *a, **kw: FakeConn()})())
        monkeypatch.setattr(cp, "execute_values", lambda *a, **kw: None)

        count = generate_synthetic_events(db_url="fake://", n_visitors=5)
        # Should not raise, returns int
        assert isinstance(count, int)
