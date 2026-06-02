# AI Store Intelligence System

**Production-grade Real-Time CCTV Retail Analytics Platform**

An end-to-end computer vision pipeline that transforms raw retail store video feeds into structured business intelligence. Leveraging YOLOv8 for person detection, ByteTrack for tracking, and a custom spatial-temporal event engine, the platform computes real-time customer journey analytics, zone heatmaps, dwell times, and anomaly alerts—served via robust REST APIs and an interactive Streamlit dashboard.

---

## 🏗️ System Architecture

```
[ CCTV Feed / Video Source ]
            │
            ▼
┌──────────────────────────────────────┐
│       Perception Layer (AI)          │
│  - YOLOv8 Person Detection           │
│  - ByteTrack Multi-Object Tracking   │
└──────────────────┬───────────────────┘
                   │ Bounding boxes + Track IDs
                   ▼
┌──────────────────────────────────────┐
│       Reasoning & Event Engine       │
│  - Custom Zone Manager               │
│  - Spatial-Temporal Re-entry Handler │
│  - Heuristic Anomaly Rules           │
└──────────────────┬───────────────────┘
                   │ Structured StoreEvent Data
                   ▼
┌──────────────────────────────────────┐
│           Storage Layer              │
│  - PostgreSQL 16 (Relational/JSONB)  │
│  - Redis 7 (Rate Limiting/Cache)     │
└──────────────────┬───────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
┌─────────────────┐ ┌──────────────────┐
│ FastAPI REST API│ │ Streamlit UI     │
│ - REST Services │ │ - Live Analytics │
│ - WebSockets    │ │ - Interactive    │
└─────────────────┘ └──────────────────┘
```

---

## 🛠️ Technology Stack

* **Computer Vision**: YOLOv8 (Ultralytics), ByteTrack (Roboflow Supervision), OpenCV
* **Backend Framework**: FastAPI (Uvicorn, Pydantic v2, SQLAlchemy)
* **Database**: PostgreSQL 16 (using GIN indexes on JSONB for schema-free metadata)
* **Caching**: Redis 7
* **Frontend/Visuals**: Streamlit (Dashboard), React + Three.js (3D Interactive Gallery)
* **Infrastructure**: Docker & Docker Compose
* **Testing**: Pytest (Pytest-Cov, SQLite In-Memory with StaticPool for thread-isolated integration checks)

---

## 🚀 Quick Start & Setup

### Prerequisites
* Docker Desktop installed and running
* Git

### Start All Services (Zero Manual Intervention)

1. Clone this repository:
   ```bash
   git clone https://github.com/zairakhaan786/Store-Intelligence-System-for-a-retail-CCTV-analytics-
   cd "Store Intelligence System for a retail CCTV analytics challenge"
   ```

2. Spin up the entire multi-service stack with a single command:
   ```bash
   docker compose up --build
   ```

3. **What happens automatically**:
   - PostgreSQL initializes the database schema, creating tables for events, sessions, occupancy, anomalies, and camera configurations.
   - The pipeline container starts, generates realistic synthetic store traffic to seed the database, and exits successfully.
   - The FastAPI server starts, exposing endpoints on port `8000`.
   - The Streamlit dashboard starts on port `8501`.
   - The 3D React Three.js WebGL gallery starts on port `3000`.

---

## 🌐 Endpoint Reference

### FastAPI Services
The REST API is exposed at `http://localhost:8000`. Interactive documentation is available at `http://localhost:8000/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| **GET** | `/metrics` | Primary store KPIs (Entries, Exits, Unique Visitors, Conversion Rate, etc.) |
| **GET** | `/metrics/funnel` | Session-based customer journey funnel analysis |
| **GET** | `/metrics/occupancy` | Real-time counts and capacity utilization per zone |
| **GET** | `/metrics/heatmap` | Normalized coordinates and visit frequencies |
| **GET** | `/events` | Paginated and filterable event logs |
| **GET** | `/anomalies` | Active alarms (overcrowding, tailgating, loitering) |
| **POST** | `/pipeline/run` | Triggers a custom pipeline execution |
| **GET** | `/health` | Server and database health check |

---

## 🏬 Store Layout Configuration

The system maps store activities dynamically using a normalized `[0, 1]` polygon coordinate space. The default store layout defines the following layout:

* **ENTRY_MAIN**: Main Entrance (Zone types: `entry`, Camera: `CAM_01`)
* **AISLE_A**: Skincare Aisle (Zone types: `aisle`, Camera: `CAM_02`)
* **AISLE_B**: Makeup Aisle (Zone types: `aisle`, Camera: `CAM_03`)
* **BEAUTY_BAR**: Experiential Station (Zone types: `beauty_bar`, Camera: `CAM_04`)
* **CHECKOUT**: POS / Checkout counter (Zone types: `checkout`, Camera: `CAM_05`)
* **EXIT_MAIN**: Main Exit (Zone types: `exit`, Camera: `CAM_01`)

---

## 🔄 Core Edge Case Handlers

* **Customer Re-entry Deduplication**: Customers exiting and re-entering the store within 30 seconds are matched using a spatial-temporal bounding box IoU calculation, preventing inflation of the unique visitor metric.
* **Group Entry Detection**: Entries are monitored using a 2-second sliding window. When 3 or more people enter concurrently, a group entry event is raised.
* **Transient Occlusion**: ByteTrack's low-confidence detection matching buffer preserves track continuity through brief occlusion states (e.g., passing behind columns or fixtures).
* **Staff Member Filtering**: Identified via path patterns and dwell times exceeding 45 minutes without checkout interactions; staff statistics are automatically filtered out from store conversion KPIs.

---

## 🧪 Local Testing

Tests run in an isolated in-memory SQLite database using `StaticPool` to verify database integrations without Docker:

```bash
# Set up local virtual environment
python -m venv venv
source venv/bin/activate
pip install -r requirements/api.txt
pip install -r requirements/pipeline.txt
pip install pytest pytest-cov

# Run the test suite with coverage
PYTHONPATH=. pytest tests/ --cov=src -v
```

---

## 🔮 Future Improvements

1. **Appearance-Based Re-Identification (ReID)**: Integrate a lightweight appearance embedding extractor (e.g., OSNet) to handle cross-camera customer tracking.
2. **Predictive Analytics**: Run LSTM/Prophet time-series models on occupancy records to forecast peak hours and staffing requirements.
3. **Queue Dwell-Time Estimations**: Track customer queue lines at checkout to raise alert flags for staff reallocation.
