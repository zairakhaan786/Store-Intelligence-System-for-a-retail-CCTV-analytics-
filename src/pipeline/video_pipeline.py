"""
OpenCV Video Pipeline — full end-to-end CCTV processing.

Ties together: video reader → detector → tracker → face detector → event engine → DB writer

Usage:
    python -m src.pipeline.video_pipeline --source 0           # webcam
    python -m src.pipeline.video_pipeline --source video.mp4   # video file
    python -m src.pipeline.video_pipeline --source rtsp://...  # RTSP stream
    python -m src.pipeline.video_pipeline --demo               # synthetic demo (no video)

Design:
- Frame-by-frame processing with configurable skip_frames for CPU efficiency
- Results written to PostgreSQL in batches (every 30 frames = ~1 second at 25fps)
- Optional visualization with annotated output frame
- Graceful shutdown on SIGINT/SIGTERM
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import supervision as sv

from src.pipeline.detector import PersonDetector
from src.pipeline.event_engine import EventEngine, StoreEvent
from src.pipeline.face_detector import FaceDetector
from src.pipeline.tracker import PersonTracker
from src.pipeline.zone_manager import ZoneManager
from src.shared.config import settings
from src.shared.logger import configure_logging, get_logger

configure_logging(settings.log_level)
logger = get_logger(__name__)

BATCH_FLUSH_FRAMES = 30
SKIP_FRAMES = 2   # Process every Nth frame (skip 2 = process every 3rd)


def _clean_for_json(obj: Any) -> Any:
    """Recursively convert numpy types to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_for_json(x) for x in obj]
    elif hasattr(obj, "item"):
        return obj.item()
    return obj


class VideoPipeline:
    """
    End-to-end CCTV processing pipeline.

    Processes video source frame-by-frame and persists structured events.
    """

    def __init__(
        self,
        camera_id: str = "CAM_01",
        source: str | int = 0,
        db_url: Optional[str] = None,
        enable_face: bool = True,
        enable_display: bool = False,
        skip_frames: int = SKIP_FRAMES,
    ) -> None:
        self._camera_id = camera_id
        self._source = source
        self._db_url = db_url or settings.database_url
        self._enable_face = enable_face
        self._enable_display = enable_display
        self._skip_frames = skip_frames

        # Pipeline components
        self._detector = PersonDetector()
        self._tracker = PersonTracker()
        self._zone_manager = ZoneManager()
        self._event_engine = EventEngine(camera_id=camera_id)
        self._face_detector = FaceDetector() if enable_face else None

        # Stats
        self._frame_count = 0
        self._event_count = 0
        self._start_time = 0.0
        self._running = False

        # Register shutdown handler
        try:
            signal.signal(signal.SIGINT, self._shutdown)
            signal.signal(signal.SIGTERM, self._shutdown)
        except ValueError:
            logger.warning("Could not register signal handlers (running in background thread)")

    def run(self, max_frames: Optional[int] = None) -> Dict:
        """
        Run the pipeline on the video source.

        Args:
            max_frames: Stop after this many frames (None = run indefinitely)

        Returns:
            Summary dict with statistics
        """
        import cv2
        from pathlib import Path

        logger.info("Starting video pipeline", source=self._source, camera=self._camera_id)
        cap = cv2.VideoCapture(self._source)

        if not cap.isOpened():
            logger.error("Cannot open video source", source=self._source)
            return {"error": "Cannot open video source"}

        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        logger.info("Video opened", fps=fps, size=f"{width}×{height}")

        # Setup VideoWriter
        out_dir = Path("data/processed")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{self._camera_id}_processed.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out_writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))
        logger.info("VideoWriter setup", path=str(out_path))

        self._start_time = time.time()
        self._running = True
        pending_events: List[StoreEvent] = []
        
        last_tracked = sv.Detections.empty()
        last_events = []

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    logger.info("End of video stream")
                    break

                self._frame_count += 1

                # If processed frame, run YOLO & Tracking
                if self._frame_count % (self._skip_frames + 1) == 0:
                    frame_timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 or time.time()

                    # ── Detection ─────────────────────────────────────────────
                    detections = self._detector.detect(frame)

                    # ── Tracking ──────────────────────────────────────────────
                    tracked = self._tracker.update(detections, frame)

                    # ── Face detection (optional) ─────────────────────────────
                    if self._face_detector and len(tracked) > 0:
                        face_dets = self._face_detector.detect(frame)

                    # ── Event generation ──────────────────────────────────────
                    events = self._event_engine.process_frame(tracked, frame, frame_timestamp)
                    pending_events.extend(events)
                    self._event_count += len(events)

                    last_tracked = tracked
                    last_events = events

                    # ── Batch flush to DB ─────────────────────────────────────
                    if len(pending_events) >= BATCH_FLUSH_FRAMES:
                        self._flush_events(pending_events)
                        pending_events.clear()

                if max_frames and self._frame_count > max_frames:
                    break

                # Annotate and write frame (always write frame so video length matches input)
                annotated = self._annotate_frame(frame, last_tracked, last_events)
                out_writer.write(annotated)

                # ── Optional visualization ────────────────────────────────
                if self._enable_display:
                    cv2.imshow(f"Store Intelligence — {self._camera_id}", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                # ── FPS logging every 300 processed frames ────────────────
                if self._frame_count % 300 == 0:
                    elapsed = time.time() - self._start_time
                    proc_fps = self._frame_count / max(elapsed, 0.001)
                    logger.info(
                        "Pipeline progress",
                        frames=self._frame_count,
                        events=self._event_count,
                        fps=round(proc_fps, 1),
                    )

        except Exception as exc:
            logger.error("Pipeline error", error=str(exc), exc_info=True)
        finally:
            # Flush remaining events
            if pending_events:
                self._flush_events(pending_events)
            cap.release()
            out_writer.release()
            logger.info("VideoWriter released", path=str(out_path))
            if self._enable_display:
                import cv2
                cv2.destroyAllWindows()

        elapsed = time.time() - self._start_time
        summary = {
            "camera_id": self._camera_id,
            "frames_processed": self._frame_count,
            "events_generated": self._event_count,
            "duration_seconds": round(elapsed, 2),
            "avg_fps": round(self._frame_count / max(elapsed, 0.001), 1),
            "processed_video_path": str(out_path),
        }
        logger.info("Pipeline complete", **summary)
        return summary

    def _flush_events(self, events: List[StoreEvent]) -> None:
        """Send event batch to the REST API for processing and session creation."""
        if not events:
            return
        try:
            import requests
            payload = []
            for ev in events:
                payload.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_002",
                    "camera_id": ev.camera_id,
                    "visitor_id": ev.track_id,
                    "event_type": ev.event_type,
                    "timestamp": datetime.fromtimestamp(ev.timestamp, tz=timezone.utc).isoformat(),
                    "zone_id": ev.zone_id,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": ev.confidence,
                    "metadata": {"frame_number": ev.frame_number, "bbox": ev.bbox}
                })
            
            resp = requests.post("http://127.0.0.1:8000/events/ingest", json=payload, timeout=10)
            if resp.status_code == 200:
                logger.debug("Events flushed via API", count=len(events))
            else:
                logger.error("API event ingest failed", status=resp.status_code, text=resp.text)
        except Exception as exc:
            logger.error("Event flush failed", error=str(exc))

    def _annotate_frame(
        self,
        frame: np.ndarray,
        tracked,
        events: List[StoreEvent],
    ) -> np.ndarray:
        """Draw bounding boxes, track IDs, and event labels on frame."""
        import cv2

        annotated = frame.copy()
        h, w = frame.shape[:2]

        # Draw Entry line (Green)
        entry_y = int(settings.entry_line_y_ratio * h)
        cv2.line(annotated, (0, entry_y), (w, entry_y), (0, 255, 0), 2)
        cv2.putText(annotated, "ENTRY THRESHOLD LINE", (10, entry_y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Draw Exit line (Red)
        exit_y = int(settings.exit_line_y_ratio * h)
        cv2.line(annotated, (0, exit_y), (w, exit_y), (0, 0, 255), 2)
        cv2.putText(annotated, "EXIT THRESHOLD LINE", (w - 200, exit_y + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        if tracked.tracker_id is not None:
            for i, tid in enumerate(tracked.tracker_id):
                bbox = tracked.xyxy[i].astype(int)
                x1, y1, x2, y2 = bbox
                color = self._id_to_color(int(tid))
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                label = f"ID:{tid}"
                cv2.putText(annotated, label, (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # Show recent events as overlay
        y_offset = 30
        for ev in events[-5:]:  # show last 5 events
            text = f"{ev.event_type.upper()} | T:{ev.track_id} | Z:{ev.zone_id}"
            cv2.putText(annotated, text, (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            y_offset += 20

        # FPS counter
        elapsed = time.time() - self._start_time
        fps = round(self._frame_count / max(elapsed, 0.001), 1)
        cv2.putText(annotated, f"FPS: {fps} | Events: {self._event_count}",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        return annotated

    @staticmethod
    def _id_to_color(track_id: int) -> tuple:
        """Generate a deterministic color for a track ID."""
        np.random.seed(track_id % 100)
        return tuple(int(c) for c in np.random.randint(50, 255, 3))

    def _shutdown(self, signum, frame):
        logger.info("Shutdown signal received")
        self._running = False





if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Store Intelligence Video Pipeline")
    parser.add_argument("--source", default="0", help="Video source: 0=webcam, file path, or RTSP URL")
    parser.add_argument("--camera-id", default="CAM_01", help="Camera identifier")
    parser.add_argument("--display", action="store_true", help="Show annotated video window")
    parser.add_argument("--max-frames", type=int, default=None, help="Stop after N frames")
    parser.add_argument("--skip-frames", type=int, default=2, help="Skip N frames between processing")
    args = parser.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    pipeline = VideoPipeline(
        camera_id=args.camera_id,
        source=source,
        enable_display=args.display,
        skip_frames=args.skip_frames,
    )
    result = pipeline.run(max_frames=args.max_frames)
    print(json.dumps(result, indent=2))
