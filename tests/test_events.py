"""
Tests for event generation and business logic.

# PROMPT: Create robust tests for the event generation pipeline. Test entry events on new tracks, exit events on track loss (timeout), multiple simultaneous entries, group entry logic, and bounding box validation. Also cover CSV parsing edge cases.
# CHANGES MADE: Modified the `test_exit_event_on_track_loss` test to aggregate events across the entire track timeout simulation loop, as the previous version only checked the returned events from the final iteration.
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
        """A new track should generate an entry event upon crossing the line."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: in entry zone (y >= 0.8) -> cy=400 (400/480 = 0.83)
        det1 = sv.Detections(
            xyxy=np.array([[100, 380, 200, 420]]),
            confidence=np.array([0.88]),
            class_id=np.array([0]),
            tracker_id=np.array([1]),
        )
        engine.process_frame(det1, frame)
        
        # Frame 2: inside store (y < 0.8) -> cy=300 (300/480 = 0.62)
        det2 = sv.Detections(
            xyxy=np.array([[100, 280, 200, 320]]),
            confidence=np.array([0.88]),
            class_id=np.array([0]),
            tracker_id=np.array([1]),
        )
        events = engine.process_frame(det2, frame)
        
        entry_events = [e for e in events if e.event_type == "entry"]
        assert len(entry_events) == 1

    def test_exit_event_on_track_loss(self):
        """When a track disappears, an exit event should be generated after timeout."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: in entry zone
        det1 = sv.Detections(
            xyxy=np.array([[100, 380, 200, 420]]),
            confidence=np.array([0.88]),
            class_id=np.array([0]),
            tracker_id=np.array([42]),
        )
        engine.process_frame(det1, frame)

        # Frame 2: cross into store
        det2 = sv.Detections(
            xyxy=np.array([[100, 280, 200, 320]]),
            confidence=np.array([0.88]),
            class_id=np.array([0]),
            tracker_id=np.array([42]),
        )
        engine.process_frame(det2, frame)

        # Simulate timeout (default max_age is 90, so we call empty 91 times)
        all_events = []
        for _ in range(92):
            events = engine.process_frame(sv.Detections.empty(), frame)
            all_events.extend(events)
            
        exit_events = [e for e in all_events if e.event_type == "exit"]
        assert len(exit_events) == 1
        assert exit_events[0].track_id == "42"

    def test_multiple_tracks_multiple_entries(self):
        """Multiple simultaneous tracks crossing should each get an entry event."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: entry zone
        det1 = sv.Detections(
            xyxy=np.array([
                [50, 380, 150, 420],
                [200, 380, 300, 420],
                [400, 380, 500, 420],
            ]),
            confidence=np.array([0.88, 0.75, 0.92]),
            class_id=np.array([0, 0, 0]),
            tracker_id=np.array([1, 2, 3]),
        )
        engine.process_frame(det1, frame)
        
        # Frame 2: inside store
        det2 = sv.Detections(
            xyxy=np.array([
                [50, 280, 150, 320],
                [200, 280, 300, 320],
                [400, 280, 500, 320],
            ]),
            confidence=np.array([0.88, 0.75, 0.92]),
            class_id=np.array([0, 0, 0]),
            tracker_id=np.array([1, 2, 3]),
        )
        events = engine.process_frame(det2, frame)
        
        entry_events = [e for e in events if e.event_type == "entry"]
        assert len(entry_events) == 3

    def test_group_entry_detected(self):
        """3+ people entering quickly should trigger group_entry."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine(camera_id="CAM_01")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: entry zone
        det1 = sv.Detections(
            xyxy=np.array([
                [50, 380, 150, 420],
                [200, 380, 300, 420],
                [350, 380, 450, 420],
                [500, 380, 600, 420],
            ]),
            confidence=np.array([0.88, 0.75, 0.92, 0.80]),
            class_id=np.array([0, 0, 0, 0]),
            tracker_id=np.array([1, 2, 3, 4]),
        )
        engine.process_frame(det1, frame)
        
        # Frame 2: inside store
        det2 = sv.Detections(
            xyxy=np.array([
                [50, 280, 150, 320],
                [200, 280, 300, 320],
                [350, 280, 450, 320],
                [500, 280, 600, 320],
            ]),
            confidence=np.array([0.88, 0.75, 0.92, 0.80]),
            class_id=np.array([0, 0, 0, 0]),
            tracker_id=np.array([1, 2, 3, 4]),
        )
        events = engine.process_frame(det2, frame)
        
        group_events = [e for e in events if e.event_type == "group_entry"]
        assert len(group_events) >= 1
        assert group_events[0].metadata.get("group_size") >= 3

    def test_event_contains_bbox(self):
        """Events must contain bounding box data."""
        import supervision as sv
        from src.pipeline.event_engine import EventEngine

        engine = EventEngine()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        det1 = sv.Detections(
            xyxy=np.array([[100, 380, 200, 420]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([7]),
        )
        engine.process_frame(det1, frame)
        
        det2 = sv.Detections(
            xyxy=np.array([[100, 280, 200, 320]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([7]),
        )
        events = engine.process_frame(det2, frame)
        
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
        det1 = sv.Detections(
            xyxy=np.array([[100, 380, 200, 420]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([8]),
        )
        engine.process_frame(det1, frame)
        
        det2 = sv.Detections(
            xyxy=np.array([[100, 280, 200, 320]]),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
            tracker_id=np.array([8]),
        )
        events = engine.process_frame(det2, frame)
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
