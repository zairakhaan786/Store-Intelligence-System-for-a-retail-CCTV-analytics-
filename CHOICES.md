# CHOICES.md — Engineering Decisions & Tradeoffs

## Store Intelligence System
### Engineering Design Choices

> This document explains **why** we made each major technical decision,
> what alternatives were considered, and what tradeoffs we accepted.
> Strong engineering is about making **justified choices**, not perfect ones.

---

## Decision 1: YOLOv8n over YOLOv8m/l/x

**Choice**: YOLOv8n (nano, 3.2M params)

**Alternatives**:
| Model | mAP50 | FPS (CPU) | Size |
|-------|--------|-----------|------|
| YOLOv8n | 37.3 | ~80 | 6.3 MB |
| YOLOv8s | 44.9 | ~45 | 22 MB |
| YOLOv8m | 50.2 | ~25 | 52 MB |
| YOLOv8l | 52.9 | ~14 | 87 MB |

**Reasoning**: Retail store analytics doesn't need 52.9 mAP. The difference between "there are 15 people" and "there are 16 people" is not business-critical. What matters is:
1. Real-time inference (>25 FPS to match camera frame rate)
2. CPU deployability (no GPU required in Docker)
3. Low memory footprint (runs alongside API + DB on a single server)

**Accepted tradeoffs**:
- ~13% lower mAP vs. YOLOv8m — acceptable for counting accuracy within ±10% error margin
- Higher false negative rate for very small/distant people — mitigated by camera positioning guidelines

**Upgrade path**: A single config change (`YOLO_MODEL=yolov8m.pt`) upgrades detection accuracy when GPU is available.

---

## Decision 2: ByteTrack via supervision over raw ByteTrack C++

**Choice**: `supervision.ByteTracker` (Python wrapper)

**Alternatives considered**:
1. **Raw ByteTrack** (C++ repo by ifzhang) — requires CUDA, complex build, no Python API
2. **DeepSORT** — adds ReID model, 3× slower, better cross-camera but overkill for single-cam
3. **SORT** — no low-confidence detection buffer → worse occlusion handling
4. **StrongSORT** — improved appearance features but requires GPU for feature extraction

**Reasoning**: The `supervision` library (by Roboflow) wraps ByteTrack with:
- Clean Python API: `tracker.update_with_detections(detections)`
- No GPU requirement
- Same core algorithm as the original paper
- Active maintenance and documentation

**Accepted tradeoffs**:
- Cannot use custom ReID features (appearance-based matching) without modifying supervision internals
- Slightly different hyperparameter interface than original ByteTrack repo

---

## Decision 3: Rule-based Anomaly Detection over ML-based

**Choice**: Rule-based detection (threshold + hysteresis)

**Alternative considered**: ML-based anomaly detection (Isolation Forest, Autoencoder, LSTM)

**Reasoning for rules**:
1. **Interpretability**: "Zone exceeded 90% capacity for 60 seconds" is explainable to store managers. "Anomaly score 0.83" is not.
2. **No training data required**: We have no labeled historical anomaly data
3. **Tunable**: Store managers can adjust thresholds without retraining
4. **Deterministic**: Same input always produces same output — easier to debug
5. **Low latency**: O(1) per check, no model inference

**When ML would be better**:
- Detecting novel/unknown anomaly patterns
- Multi-variate anomalies (e.g., occupancy + temperature + time-of-day combined)
- After 6+ months of labeled data collection

**Accepted tradeoffs**:
- Cannot detect anomaly types we haven't explicitly coded
- Threshold tuning requires domain expertise
- No adaptive learning from historical patterns

---

## Decision 4: PostgreSQL over MongoDB or InfluxDB

**Choice**: PostgreSQL 16 with JSONB

**Alternatives**:
| DB | Pros | Cons |
|----|------|------|
| MongoDB | Schema flexibility | No ACID, complex joins |
| InfluxDB | Time-series native | Poor for ad-hoc event queries |
| Redis | Ultra-fast | Volatile, not for analytics |
| SQLite | Zero setup | No concurrent writes, no network |

**Reasoning**: The data has **two natures**:
1. Structured (track_id, event_type, timestamp) → benefits from SQL joins for funnel queries
2. Semi-structured (event metadata varies by type) → JSONB handles this without extra tables

PostgreSQL with JSONB gives us the best of both: `WHERE metadata->>'anomaly_type' = 'loitering'` works perfectly.

**Accepted tradeoffs**:
- More complex setup than SQLite (requires separate container)
- JSONB queries slightly slower than pure relational — acceptable at retail-store scale (<10M events/day)

---

## Decision 5: Session-based Visitor Counting over Event-based

**Choice**: Sessions table with `session_index` for re-entry deduplication

**Alternative**: Count all `entry` events (simpler but wrong)

**The problem with raw event counting**:
```
Customer enters → 1 entry event
Customer exits  → 1 exit event
Customer re-enters → 1 MORE entry event (same person!)

Naive count: 2 unique visitors
Correct count: 1 unique visitor, 2 visits
```

**Our approach**:
- First entry (session_index=0): counted as unique visitor
- Re-entries (session_index>0): counted as re-entry, not unique visitor
- `unique_visitors = COUNT(DISTINCT track_id WHERE event_type='entry')`

**Accepted tradeoffs**:
- Slightly more complex query logic
- Re-entry detection accuracy depends on IoU threshold (may miss some re-entries with 0% IoU)

---

## Decision 6: Spatial-Temporal IoU for Re-entry Detection over ReID

**Choice**: Spatial-temporal IoU matching (simple, CPU-fast)

**Alternative**: Appearance-based ReID (OSNet, FastReID, Torchreid)

**Reasoning**:
- ReID models require GPU inference (50-200ms per query)
- OSNet model is 2.2MB but needs CUDA for real-time use
- At 25 FPS with 10 active tracks, ReID would bottleneck the pipeline
- Spatial IoU works well for single-camera, single-entrance scenario (common in retail)

**Accuracy comparison** (estimated):
| Method | Re-entry Detection Accuracy | Latency |
|--------|----------------------------|---------|
| Spatial IoU | ~75-85% (same entrance) | <1ms |
| ReID (OSNet) | ~90-95% (any entrance) | 50-200ms |

**When ReID would be worth it**: Multi-camera store (person exits CAM_01, enters CAM_02)

**Accepted tradeoffs**:
- ~15-20% miss rate for re-entries (acceptable for analytics; exact count not required)
- Will fail for cross-camera re-entry scenarios

---

## Decision 7: supervision.PolygonZone over Custom Zone Logic

**Choice**: supervision.PolygonZone for zone containment testing

**Alternative**: Custom ray-casting polygon test

**Reasoning**: We actually implemented our own ray-casting in `zone_manager.py` for flexibility, but the supervision library's PolygonZone is used for frame-level batch testing (much faster for 10+ zones × 10+ tracks per frame).

The custom implementation gives us normalized coordinate support (0–1 range) which supervision doesn't support natively.

---

## Decision 8: Streamlit over React for Dashboard

**Choice**: Streamlit (Python-native)

**Alternative**: React + Recharts/D3.js

**Reasoning**:
- Streamlit can be built and maintained by a single developer in hours
- Python ecosystem: same language as pipeline, direct httpx API calls
- Plotly integration is excellent for heatmaps, funnels, and time-series
- No frontend build system required (no webpack, npm, CI pipeline)

**We also built a React 3D Gallery** for the futuristic interaction use case, which React/Three.js is purpose-built for.

**Accepted tradeoffs**:
- Streamlit reloads entire page on widget interaction (not true SPA)
- Limited to Streamlit's theming system
- Cannot do complex gesture-controlled animations

---

## Decision 9: Synthetic Data Generator over Requiring CSV Upload

**Choice**: Built-in synthetic data generator (`csv_processor.py::generate_synthetic_events`)

**Reasoning**: The production-ready deployment requires `docker compose up` to work out-of-the-box. Generating initial seed data ensures the analytics dashboard is immediately populated and operational for demonstration.

The synthetic generator:
- Creates 50+ realistic visitor sessions
- Covers all event types (entry, exit, reentry, group, anomaly)
- Uses realistic timing (9am-9pm spread, realistic dwell times)
- Runs automatically on first startup

**Problem with alternative**: Fails to provide an out-of-the-box demonstration of the system's capabilities.

---

## Decision 10: Docker Multi-Service Architecture

**Choice**: 4 separate containers (postgres, pipeline, api, dashboard)

**Alternative**: Single container with supervisord

**Reasoning**:
- **Single responsibility**: Each container has one job, fails independently
- **Independent scaling**: API can be scaled to N replicas without scaling the dashboard
- **Health checks**: Docker Compose can wait for `postgres:healthy` before starting `api`
- **Volume isolation**: DB data persists independently of application containers

**Startup dependency chain**:
```
postgres (healthy) → pipeline (seed, exit) → api (healthy) → dashboard (start)
```

**Accepted tradeoffs**:
- Longer cold-start (~60s for all services to be healthy)
- More complex docker-compose.yml
- Requires Docker Compose v2.20+ for `service_completed_successfully` condition

---

## Decision 11: FastAPI over Flask or Django

**Choice**: FastAPI (Starlette + Pydantic)

**Alternatives**:
| Framework | Pros | Cons |
|-----------|------|------|
| Flask | Familiar, simple | No async, manual validation, no OpenAPI |
| Django REST | Full-featured | Heavy, too much for an API-only service |
| FastAPI | Async, Pydantic, auto-OpenAPI | Newer, smaller ecosystem |

**Reasoning**:
- Pydantic v2 validation with zero boilerplate
- Auto-generated OpenAPI/Swagger at `/docs`
- Async-native (handles I/O-bound DB queries efficiently)
- Response model enforcement prevents leaking internal fields

---

## Decision 12: Normalized Zone Polygons [0,1] over Pixel Coordinates

**Choice**: All zone polygons stored in normalized [0,1] coordinate space

**Reasoning**:
- A 1080p camera and a 720p camera covering the same zone use the same polygon definition
- Camera resolution can change (compression settings, upgrade) without updating zone configs
- Makes zone configs camera-agnostic — same JSON in DB, scales at inference time

**Implementation**: `pixel_poly = (normalized_poly * np.array([W, H])).astype(int)`

---

## Decision 13: JSONB metadata over Type-Specific Event Tables

**Choice**: Single `events` table with JSONB `metadata` column

**Alternative**: Separate tables per event type (entry_events, exit_events, anomaly_events...)

**Reasoning**:
- Adding new event types requires no schema migration
- Unified query interface: `SELECT * FROM events WHERE event_type = 'reentry'`
- JSONB supports GIN indexing for fast key queries

**Alternative problem**: Each new event type requires a new table, join query, and ORM model — exponential maintenance burden.

---

## Decision 14: Confidence Threshold 0.35 over 0.5 (default)

**Choice**: `YOLO_CONFIDENCE=0.35`

**Reasoning**: Retail CCTV has several challenging conditions:
- Partial occlusion (behind shelves, other shoppers): reduces confidence to 0.4–0.5
- Camera angle (top-down): different from training data distribution
- Low light (evening hours): affects color channels

Setting threshold to 0.35 catches these edge cases while still filtering mannequins and display props (which typically score <0.25).

**ByteTrack benefit**: Low-confidence detections (0.35–0.5) still feed ByteTrack's second-stage matching buffer, improving track continuity through occlusion.

**Accepted tradeoff**: ~5% higher false positive rate vs. default 0.5 threshold — acceptable for counting use case.

---

## Summary Table

| Decision | Choice | Key Reason | Main Tradeoff |
|----------|--------|-----------|---------------|
| Detection | YOLOv8n | CPU speed | -13% mAP vs. large models |
| Tracking | ByteTrack (supervision) | No GPU, clean API | No cross-cam ReID |
| Anomaly | Rule-based | Interpretable | Can't detect novel patterns |
| Database | PostgreSQL + JSONB | SQL + flexibility | More setup than SQLite |
| Counting | Session-based | Correct dedup | More complex queries |
| Re-entry | Spatial IoU | CPU-fast, <1ms | Misses cross-cam re-entry |
| Dashboard | Streamlit | Fast to build | Not true SPA |
| Data | Synthetic generator | Zero manual setup | Not real CCTV data |
| Zones | Normalized [0,1] | Resolution-independent | Extra scaling step |
| Events | JSONB metadata | Schema-free | Slightly slower than typed |
| API | FastAPI | Pydantic + OpenAPI | Smaller ecosystem than Django |
| Confidence | 0.35 (not 0.5) | Handles occlusion | +5% false positives |

---

*"A professional production system is one that makes reasonable trade-offs, works reliably out-of-the-box, and is cleanly documented."*
