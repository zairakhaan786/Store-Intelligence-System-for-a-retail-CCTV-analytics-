# DESIGN.md — System Architecture

## Store Intelligence System
### AI Store Intelligence System

---

## 1. Problem Decomposition

Raw CCTV footage is unstructured signal. The goal is to transform it into business intelligence — specifically:

| Raw Signal | Business Metric |
|-----------|----------------|
| Pixel changes between frames | Person detected |
| Tracked bounding box trajectory | Visitor journey |
| Track appearing at entry line | Store entry event |
| Track disappearing + reappearing | Re-entry event |
| Multiple tracks at same point | Group / crowd |
| Track stationary > threshold | Loitering / dwell |
| Track at checkout zone | Conversion |

The system is designed around **4 stages**: Perceive → Track → Reason → Report.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        PERCEPTION LAYER                          │
│                                                                  │
│  CCTV Video / CSV ──► YOLOv8n ──► ByteTrack ──► FaceDetector   │
│                         person      track_id     face regions    │
│                        detection    assignment    (OpenCV DNN)   │
└─────────────────────────────┬────────────────────────────────────┘
                              │ tracked detections per frame
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                         REASONING LAYER                          │
│                                                                  │
│  EventEngine ──────────────────────────────────────────────────  │
│  │  entry / exit / zone_enter / zone_exit                        │
│  │  group_entry / reentry                                        │
│  │                                                               │
│  ├── ReEntryHandler ──── spatial-temporal IoU matching           │
│  ├── AnomalyDetector ─── rule-based overcrowding/loitering       │
│  ├── ZoneManager ──────── polygon containment testing            │
│  └── OccupancyAnalyzer ── density + heatmap computation          │
│                                                                  │
│  GestureController ─── MediaPipe Hands ─► gesture events        │
└─────────────────────────────┬────────────────────────────────────┘
                              │ StoreEvent objects
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                            │
│                                                                  │
│  PostgreSQL 16                                                   │
│  ├── events      (all pipeline events, JSONB metadata)           │
│  ├── sessions    (per-visitor journeys, is_complete flag)        │
│  ├── occupancy   (time-series, 1-minute buckets)                 │
│  ├── anomalies   (active anomalies with resolution tracking)     │
│  ├── gestures    (gesture interaction log)                       │
│  ├── zones       (store layout polygon definitions)              │
│  └── cameras     (camera registry)                              │
└─────────────────────────────┬────────────────────────────────────┘
                              │ SQL queries
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                          API LAYER                               │
│                                                                  │
│  FastAPI (uvicorn, 2 workers)                                    │
│  ├── GET  /metrics         ─── KPI aggregations                 │
│  ├── GET  /metrics/funnel  ─── visitor journey funnel            │
│  ├── GET  /metrics/occupancy ─ real-time zone counts            │
│  ├── GET  /metrics/heatmap ─── zone visit frequency              │
│  ├── GET  /events          ─── paginated event log               │
│  ├── GET  /anomalies       ─── active anomaly alerts             │
│  ├── GET  /visitors        ─── session-level visitor data        │
│  ├── GET  /gesture-events  ─── gesture interaction log           │
│  ├── POST /pipeline/run    ─── trigger pipeline                  │
│  ├── POST /pipeline/seed   ─── seed synthetic data               │
│  └── GET  /health          ─── health check                     │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTP/JSON
                    ┌─────────┴──────────┐
                    ▼                    ▼
     ┌──────────────────────┐  ┌────────────────────────┐
     │  Streamlit Dashboard  │  │  React 3D Gallery       │
     │  (analytics + KPIs)   │  │  (Three.js + WebGL)     │
     │  Real-time charts     │  │  3D store occupancy     │
     │  Funnel / heatmap     │  │  Floating data panels   │
     │  Anomaly alerts       │  │  Gesture navigation     │
     └──────────────────────┘  └────────────────────────┘
```

---

## 3. Detection Pipeline Design

### 3.1 YOLOv8 Detection

**Model**: YOLOv8n (nano) — 3.2M parameters, ~80 FPS on CPU

**Why YOLOv8 over alternatives**:
- Faster R-CNN: 2-stage, too slow for real-time retail analytics
- SSD: Lower accuracy in dense scenes (crowded entrances)
- YOLOv5: Predecessor — YOLOv8 is drop-in replacement with +3% mAP
- YOLOv9/v10: Not yet widely supported by supervision library

**Inference settings**:
- `conf=0.35`: Low enough to catch partially occluded people, high enough to reject display mannequins
- `iou=0.45`: Standard NMS threshold; prevents double-counting adjacent shoppers
- `classes=[0]`: Filter to person class only (reduces false positives from shopping bags, fixtures)

### 3.2 ByteTrack Tracking

**Algorithm**: ByteTrack (Zhang et al., ECCV 2022)

**Key innovation**: Two-stage association
1. High-confidence detections (conf > 0.5) matched first via IoU
2. Low-confidence detections (0.1–0.5) matched to lost tracks — this is what handles occlusion

**Parameters**:
- `lost_track_buffer=30`: Tracks held for 30 frames (~1.2s at 25fps) before retirement
- `minimum_consecutive_frames=3`: Prevents spurious tracks from mirror reflections or lighting artifacts
- `minimum_matching_threshold=0.8`: High spatial consistency required for ID assignment

### 3.3 Frame Processing Pipeline

```
Frame (BGR numpy)
    │
    ├─► YOLOv8.predict() ────► sv.Detections (xyxy, confidence, class_id)
    │
    └─► ByteTracker.update() ─► sv.Detections + tracker_id
            │
            └─► EventEngine.process_frame()
                    │
                    ├─► For each new track_id: check ReEntryHandler → emit entry/reentry
                    ├─► For each track: compute zone membership → emit zone events
                    ├─► For each lost track: emit exit, record exit for reentry detection
                    ├─► Check group entry: sliding window ≥3 entries in 2s
                    └─► Check anomalies: occupancy, dwell, loitering
```

---

## 4. Re-entry Detection Design

**Problem**: ByteTrack assigns a new ID when a person re-enters after leaving. Without deduplication, this inflates unique visitor counts.

**Solution**: Spatial-temporal IoU matching

```
Person exits frame → record ExitRecord(track_id, bbox_norm, exit_time, camera_id)
                                    │
New detection appears               │
        │                          ▼
        └─► check all ExitRecords within gap_seconds (30s)
                    │
                    └─► compute IoU(new_bbox, exit_bbox)
                                    │
                        IoU > 0.30 → RE-ENTRY detected
                        new_track_id → (original_track_id, session_index+1)
```

**Limitations of this approach**:
- False positives when two customers use same entrance point within gap window (mitigated by IoU threshold)
- Does not handle cross-camera re-entry (person exits CAM_01, enters CAM_02) — would need ReID model

**Alternative considered**: Appearance-based ReID (OSNet, FastReID)
- Pros: Cross-camera matching, higher accuracy
- Cons: GPU required, 100ms+ latency per query, complex deployment
- Decision: Spatial-temporal heuristic sufficient for single-camera, shop-scale deployment

---

## 5. Event Schema Design

All events follow a unified schema stored in the `events` table:

```json
{
  "id": "uuid-v4",
  "event_type": "entry | exit | zone_enter | zone_exit | reentry | group_entry | anomaly",
  "track_id": "string",
  "session_id": "uuid-v4",
  "camera_id": "CAM_01",
  "zone_id": "ENTRY_MAIN",
  "timestamp": "ISO 8601",
  "frame_number": 1423,
  "confidence": 0.87,
  "bbox": {"x1": 0.2, "y1": 0.3, "x2": 0.4, "y2": 0.9},
  "metadata": {
    "session_index": 0,
    "is_reentry": false,
    "group_size": 4,
    "anomaly_type": "loitering",
    "severity": "medium"
  }
}
```

**JSONB for metadata**: Allows schema evolution without migrations — new event types can carry arbitrary data without altering the table structure.

---

## 6. Session-based Business Logic

**Why sessions, not raw events?**

Raw event counting leads to double counting:
- A person entering → 1 entry event
- Same person re-entering → 1 reentry event + another session

Business metric should count **unique visitors** = distinct sessions with `session_index=0`.

**Session lifecycle**:
```
entry/reentry event
        │
        ▼
CREATE session (id, track_id, session_index, entry_time, is_complete=False)
        │
   [person moves through store]
        │
        ├── zone_enter events → append to sessions.zones_visited[]
        │
        └── exit event → UPDATE session SET exit_time, duration, is_complete=True
```

**Funnel computation**:
- Entry = COUNT(DISTINCT track_id WHERE event_type='entry')
- Aisle Browse = COUNT(DISTINCT track_id WHERE zone_id IN ('AISLE_A','AISLE_B'))
- Checkout = COUNT(DISTINCT track_id WHERE zone_id='CHECKOUT')
- Conversion = Checkout / Entry

---

## 7. Anomaly Detection Architecture

**Rule-based over ML-based** for the following reasons:
1. Interpretability — store managers can understand "zone > 90% for 60s"
2. No training data required
3. Tunable thresholds per store/zone
4. Zero false negatives for critical rules

| Anomaly | Rule | Hysteresis | Severity |
|---------|------|-----------|---------|
| Overcrowding | zone_count ≥ 0.9 × capacity | Must persist 60s | High |
| Loitering | dwell at entry/exit ≥ 120s | Per-track timer | Medium |
| Long dwell | dwell at checkout ≥ 300s | Per-track timer | Medium |
| Tailgating | ≥2 entries within 1.5s | Sliding window | Low |
| Group entry | ≥3 entries within 2.0s | Sliding window | Low |

**Hysteresis** prevents alert spamming: conditions must persist for a duration before triggering.

---

## 8. PostgreSQL Schema Design

### Key Design Decisions

**UUIDs as primary keys** (not serial integers):
- Events are distributed across cameras; UUID prevents collision without coordination
- Allows future horizontal scaling (each camera generates its own UUIDs)

**JSONB for metadata**:
- Flexible event-specific payload without schema migration
- PostgreSQL JSONB supports indexing (`CREATE INDEX ON events USING gin(metadata)`)

**Time-series occupancy table** (1-minute buckets):
- Avoids recomputing from raw events for dashboards
- `(zone_id, bucket_time)` unique constraint enables upsert

**Indices**:
```sql
CREATE INDEX idx_events_type ON events(event_type);    -- filter by type
CREATE INDEX idx_events_track ON events(track_id);    -- per-visitor queries
CREATE INDEX idx_events_ts ON events(timestamp);      -- time-range queries
CREATE INDEX idx_sessions_track ON sessions(track_id); -- session lookup
```

---

## 9. Store Zone Architecture

Zones are defined as **normalized polygons** [0,1] coordinate space:

```
Y=0.0 (top)    ┌────────────────────────┐
               │    CHECKOUT (0-20%)     │
               │────────────────────────│
               │    BEAUTY BAR (20-50%) │
               │────────────────────────│
               │ AISLE_A  │  AISLE_B   │
               │ (50-80%) │  (50-80%)  │
               │────────────────────────│
               │    ENTRY/EXIT (80-100%)│
Y=1.0 (bottom) └────────────────────────┘
```

Normalization benefits:
- Resolution-independent (works at 720p, 1080p, 4K)
- Easy to remap when camera angle/zoom changes
- Shared zone definitions across camera IDs

---

## 10. Gesture Control Architecture

```
Webcam Frame
     │
     ▼
MediaPipe Hands ──► Hand Landmarks (21 points per hand)
     │
     ▼
GestureClassifier
     ├── SWIPE_LEFT   (hand velocity: x > threshold, rightward)
     ├── SWIPE_RIGHT  (hand velocity: x < threshold, leftward)
     ├── ZOOM_IN      (two-hand pinch opening)
     ├── ZOOM_OUT     (two-hand pinch closing)
     ├── OPEN_PALM    (all fingers extended)
     └── POINT_SELECT (index finger extended, others folded)
          │
          ▼
     GestureEvent → stored to gestures table
          │
          ▼
     WebSocket broadcast → Dashboard / 3D Gallery
```

---

## 11. 3D Gallery Architecture

```
React Frontend (Vite)
     │
     ├── Three.js / React Three Fiber ── WebGL renderer
     │       ├── Store3D scene (walls, aisles, fixtures)
     │       ├── OccupancyBubbles (animated spheres per zone)
     │       ├── FloatingPanels (HTML overlay with live KPIs)
     │       └── TrackPaths (visitor journey ribbons)
     │
     └── API polling every 5s ── /metrics, /occupancy, /events
```

---

## 12. Docker Architecture

```
docker-compose.yml
     │
     ├── postgres:16-alpine
     │   └── volumes: postgres_data, db/init.sql
     │   └── healthcheck: pg_isready
     │
     ├── pipeline (Dockerfile.pipeline)
     │   └── depends_on: postgres:healthy
     │   └── runs once: seed synthetic data → exit
     │
     ├── api (Dockerfile.api)
     │   └── depends_on: postgres:healthy, pipeline:completed
     │   └── healthcheck: GET /health
     │   └── ports: 8000:8000
     │
     └── dashboard (Dockerfile.dashboard)
         └── depends_on: api:healthy
         └── healthcheck: GET /_stcore/health
         └── ports: 8501:8501
```

**Startup order**: postgres → pipeline (seed) → api → dashboard

This ensures:
1. Schema is initialized before any service queries
2. Synthetic data exists before API starts
3. API is healthy before dashboard connects

---

## 13. Scalability Considerations

**Current (single-store, demo)**: SQLite-compatible queries, single API worker

**Near-term (multi-camera)**: 
- Add Redis for real-time track state (replaces in-memory EventEngine state)
- Kafka topic per camera for event streaming
- Multiple pipeline worker pods

**Production (multi-store)**:
- Partition events table by `camera_id` + `timestamp`
- TimescaleDB extension for occupancy time-series
- CDN for dashboard static assets
- API Gateway with per-camera authentication

---

## 14. Face Detection Design

**Privacy-first approach**:
- Face detection only (not recognition/identification)
- No face images stored — only metadata (detected: bool, confidence: float)
- Face region used for: presence analytics, repeat visitor estimation (hash only)
- Compliant with GDPR Article 9 (biometric data) — no biometric templates stored

**Implementation**: OpenCV DNN (res10_300x300_ssd) for speed over Haarcascade accuracy

---

## 15. AI-Assisted Decisions

1. **Zone Containment over ReID for Funnels**
   - *AI Suggestion*: The LLM suggested implementing a FastReID model for cross-camera correlation to track a shopper journey perfectly from entry to checkout.
   - *My Decision*: Overrode. A FastReID model adds significant latency (requires GPU). Instead, I mapped the overlapping cameras to physical normalized zones in `zone_manager.py` and used a simplified session-tracking model linked by continuous timestamps. This ensures real-time compatibility at the expense of slight double-counting on camera handoffs.

2. **Database Schema Design**
   - *AI Suggestion*: The AI suggested building separate tables for `entries`, `exits`, `zone_transitions`, and `anomalies` to cleanly type the data.
   - *My Decision*: Agreed partially, but pivoted to a single `events` table with a `JSONB` metadata column. The AI was right about normalization, but a unified events stream is much easier to feed into the API `POST /events/ingest` without requiring the client pipeline to manage relational consistency across 5 tables.

3. **Dashboard Real-time Polling**
   - *AI Suggestion*: Use WebSockets (FastAPI WebSockets + React) for true real-time metric pushes to the frontend.
   - *My Decision*: Disagreed. Added Streamlit with a simple 2-second `ttl` cache loop. This drastically reduces the complexity of the Docker deployment and prevents state desync bugs when the pipeline lags, fulfilling the real-time requirement within a 5-minute development window.

---

*Architecture designed for AI Store Intelligence System*
*Author: Store Intelligence Team*
