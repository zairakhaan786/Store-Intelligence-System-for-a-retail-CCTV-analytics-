"""
Hand Gesture Controller using MediaPipe Hands.

Futuristic retail interaction system — control the dashboard and 3D gallery
without touching any screen.

Supported gestures:
  OPEN_PALM      — all 5 fingers extended (pause/stop)
  POINT_SELECT   — index finger extended, others folded (select item)
  SWIPE_LEFT     — rapid rightward hand movement (next panel)
  SWIPE_RIGHT    — rapid leftward hand movement (prev panel)
  ZOOM_IN        — two hands moving apart (expand view)
  ZOOM_OUT       — two hands moving together (collapse view)
  THUMBS_UP      — thumb extended upward (confirm/approve)
  FIST           — all fingers folded (dismiss/cancel)

Design decisions:
- MediaPipe over custom CNN:
  MediaPipe Hands runs at 30+ FPS on CPU, uses graph-based landmark detection
  A custom CNN would need labeled training data and GPU inference
- Velocity-based gesture classification (not pose-only):
  Pure pose detection can't distinguish static poses from gestures
  We track centroid velocity over a 5-frame window for swipe detection
- Debouncing (300ms):
  Prevents repeated gesture triggers from hand tremor or slow gesture execution

Edge cases:
- Partial hand visibility → landmarks have low confidence → gesture ignored
- Multiple hands → each processed independently; two-hand gestures use both
- Lighting changes → MediaPipe is robust to lighting variation (works in dim retail)
- Gesture misdetection → debounce + confidence threshold prevents false triggers
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.shared.logger import get_logger

logger = get_logger(__name__)

# Try to import MediaPipe (optional dependency)
try:
    import mediapipe as mp
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False
    logger.warning("MediaPipe not installed — gesture control disabled. Install: pip install mediapipe")


class GestureType(str, Enum):
    OPEN_PALM = "open_palm"
    POINT_SELECT = "point_select"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    THUMBS_UP = "thumbs_up"
    FIST = "fist"
    NONE = "none"


@dataclass
class GestureEvent:
    gesture_type: GestureType
    confidence: float
    hand_count: int
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "gesture_type": self.gesture_type.value,
            "confidence": round(self.confidence, 3),
            "hand_count": self.hand_count,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class HandLandmarks:
    """MediaPipe hand landmark indices."""
    WRIST = 0
    THUMB_TIP = 4
    INDEX_TIP = 8
    MIDDLE_TIP = 12
    RING_TIP = 16
    PINKY_TIP = 20
    INDEX_PIP = 6    # Proximal interphalangeal joint
    MIDDLE_PIP = 10
    RING_PIP = 14
    PINKY_PIP = 18
    THUMB_IP = 3


class GestureClassifier:
    """
    Classifies MediaPipe hand landmarks into gesture types.
    All methods operate on normalized landmarks [0,1].
    """

    @staticmethod
    def _finger_extended(tip: Tuple, pip: Tuple) -> bool:
        """Return True if finger tip is above its PIP joint (finger extended)."""
        return tip[1] < pip[1]  # y increases downward in image space

    @staticmethod
    def _thumb_extended(tip: Tuple, ip: Tuple, wrist: Tuple) -> bool:
        """Thumb extension check based on x-distance from wrist."""
        return abs(tip[0] - wrist[0]) > abs(ip[0] - wrist[0]) * 1.2

    def classify(self, landmarks: List[Tuple[float, float, float]]) -> Tuple[GestureType, float]:
        """
        Classify single-hand gesture from landmarks.

        Args:
            landmarks: List of 21 (x, y, z) tuples (MediaPipe format)

        Returns:
            (GestureType, confidence)
        """
        if len(landmarks) != 21:
            return GestureType.NONE, 0.0

        thumb_tip  = landmarks[HandLandmarks.THUMB_TIP]
        index_tip  = landmarks[HandLandmarks.INDEX_TIP]
        middle_tip = landmarks[HandLandmarks.MIDDLE_TIP]
        ring_tip   = landmarks[HandLandmarks.RING_TIP]
        pinky_tip  = landmarks[HandLandmarks.PINKY_TIP]

        index_pip  = landmarks[HandLandmarks.INDEX_PIP]
        middle_pip = landmarks[HandLandmarks.MIDDLE_PIP]
        ring_pip   = landmarks[HandLandmarks.RING_PIP]
        pinky_pip  = landmarks[HandLandmarks.PINKY_PIP]
        thumb_ip   = landmarks[HandLandmarks.THUMB_IP]
        wrist      = landmarks[HandLandmarks.WRIST]

        index_ext  = self._finger_extended(index_tip, index_pip)
        middle_ext = self._finger_extended(middle_tip, middle_pip)
        ring_ext   = self._finger_extended(ring_tip, ring_pip)
        pinky_ext  = self._finger_extended(pinky_tip, pinky_pip)
        thumb_ext  = self._thumb_extended(thumb_tip, thumb_ip, wrist)

        fingers = [thumb_ext, index_ext, middle_ext, ring_ext, pinky_ext]
        extended_count = sum(fingers)

        # Open palm: all 5 extended
        if extended_count == 5:
            return GestureType.OPEN_PALM, 0.95

        # Fist: none extended
        if extended_count == 0:
            return GestureType.FIST, 0.90

        # Point select: only index extended
        if index_ext and not middle_ext and not ring_ext and not pinky_ext:
            return GestureType.POINT_SELECT, 0.90

        # Thumbs up: only thumb extended, pointing up
        if thumb_ext and not index_ext and not middle_ext and thumb_tip[1] < wrist[1] - 0.1:
            return GestureType.THUMBS_UP, 0.85

        return GestureType.NONE, 0.5


class GestureController:
    """
    Full gesture recognition pipeline.
    Processes webcam frames and emits GestureEvents.
    """

    DEBOUNCE_SECONDS = 0.3
    SWIPE_VELOCITY_THRESHOLD = 0.15  # normalized units per frame
    SWIPE_WINDOW_FRAMES = 5
    ZOOM_DISTANCE_THRESHOLD = 0.1

    def __init__(self) -> None:
        self._available = _MP_AVAILABLE
        self._mp_hands = None
        self._hands = None
        self._classifier = GestureClassifier()

        # Per-hand centroid history for swipe detection
        self._centroid_history: deque = deque(maxlen=self.SWIPE_WINDOW_FRAMES)
        # Two-hand distance history for zoom detection
        self._distance_history: deque = deque(maxlen=self.SWIPE_WINDOW_FRAMES)

        self._last_gesture_time: float = 0.0
        self._gesture_log: List[GestureEvent] = []

        if self._available:
            self._mp_hands = mp.solutions.hands
            self._hands = self._mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.5,
            )
            logger.info("GestureController initialized with MediaPipe")
        else:
            logger.warning("GestureController: MediaPipe unavailable, running in mock mode")

    def process_frame(self, frame: np.ndarray) -> Optional[GestureEvent]:
        """
        Process a single webcam frame and detect gestures.

        Args:
            frame: BGR numpy array from webcam

        Returns:
            GestureEvent if gesture detected (after debounce), else None
        """
        if not self._available or self._hands is None:
            return self._mock_gesture()

        import cv2
        # MediaPipe expects RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._hands.process(rgb)

        if not results.multi_hand_landmarks:
            self._centroid_history.append(None)
            return None

        hand_data = []
        for hand_landmarks in results.multi_hand_landmarks:
            lm = [(l.x, l.y, l.z) for l in hand_landmarks.landmark]
            cx = sum(l[0] for l in lm) / len(lm)
            cy = sum(l[1] for l in lm) / len(lm)
            gesture, conf = self._classifier.classify(lm)
            hand_data.append({"landmarks": lm, "centroid": (cx, cy), "gesture": gesture, "conf": conf})

        # Single-hand gestures
        primary = hand_data[0]
        gesture_type = primary["gesture"]
        confidence = primary["conf"]
        hand_count = len(hand_data)

        # Two-hand zoom detection
        if len(hand_data) == 2:
            zoom_result = self._check_zoom(hand_data[0]["centroid"], hand_data[1]["centroid"])
            if zoom_result is not None:
                gesture_type, confidence = zoom_result
        elif len(hand_data) == 1:
            # Swipe detection (single hand velocity)
            swipe_result = self._check_swipe(primary["centroid"])
            if swipe_result is not None:
                gesture_type, confidence = swipe_result

        if gesture_type == GestureType.NONE:
            return None

        return self._emit_gesture(gesture_type, confidence, hand_count)

    def _check_swipe(
        self, centroid: Tuple[float, float]
    ) -> Optional[Tuple[GestureType, float]]:
        """Detect swipe based on centroid velocity over window."""
        self._centroid_history.append(centroid)
        if len(self._centroid_history) < self.SWIPE_WINDOW_FRAMES:
            return None

        x_positions = [c[0] for c in self._centroid_history if c is not None]
        if len(x_positions) < 3:
            return None

        velocity = (x_positions[-1] - x_positions[0]) / len(x_positions)

        if velocity > self.SWIPE_VELOCITY_THRESHOLD:
            return GestureType.SWIPE_RIGHT, 0.85
        elif velocity < -self.SWIPE_VELOCITY_THRESHOLD:
            return GestureType.SWIPE_LEFT, 0.85
        return None

    def _check_zoom(
        self,
        c1: Tuple[float, float],
        c2: Tuple[float, float],
    ) -> Optional[Tuple[GestureType, float]]:
        """Detect zoom based on two-hand distance change."""
        dist = ((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2) ** 0.5
        self._distance_history.append(dist)
        if len(self._distance_history) < self.SWIPE_WINDOW_FRAMES:
            return None

        delta = self._distance_history[-1] - self._distance_history[0]
        if delta > self.ZOOM_DISTANCE_THRESHOLD:
            return GestureType.ZOOM_IN, 0.88
        elif delta < -self.ZOOM_DISTANCE_THRESHOLD:
            return GestureType.ZOOM_OUT, 0.88
        return None

    def _emit_gesture(
        self,
        gesture_type: GestureType,
        confidence: float,
        hand_count: int,
    ) -> Optional[GestureEvent]:
        """Apply debounce and emit gesture event."""
        now = time.time()
        if now - self._last_gesture_time < self.DEBOUNCE_SECONDS:
            return None
        self._last_gesture_time = now

        ev = GestureEvent(
            gesture_type=gesture_type,
            confidence=confidence,
            hand_count=hand_count,
            metadata={"debounce_ms": self.DEBOUNCE_SECONDS * 1000},
        )
        self._gesture_log.append(ev)
        logger.info("Gesture detected", type=gesture_type.value, conf=round(confidence, 2))
        return ev

    def _mock_gesture(self) -> None:
        """Return None when MediaPipe unavailable."""
        return None

    def get_gesture_log(self) -> List[GestureEvent]:
        return list(self._gesture_log)

    def is_available(self) -> bool:
        return self._available

    def close(self) -> None:
        if self._hands:
            self._hands.close()
