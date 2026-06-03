# AI Store Intelligence System

**Production-grade Real-Time CCTV Retail Analytics Platform**

An end-to-end computer vision pipeline that transforms raw retail store video feeds into structured business intelligence. Leveraging **YOLOv8** for person detection, **ByteTrack** for tracking, and a custom spatial-temporal event engine, the platform computes real-time customer journey analytics, zone heatmaps, dwell times, and anomaly alerts—served via robust REST APIs and an interactive Streamlit dashboard.

---

## 🎯 Project Overview

This platform processes raw CCTV footage and outputs live, real-time analytics for a retail environment. It is designed for production use, ensuring stability, graceful error handling, and high accuracy without duplicate counting or "jitter" from tracking loss.

**Key Features:**
- **Real-Time Detection & Tracking:** YOLOv8 + ByteTrack integration with 90-frame occlusion buffering.
- **Strict Entry/Exit Logic:** Accurate zone line-crossing detection with unique ID deduplication.
- **Live Occupancy:** Real-time `MAX(0, entries - exits)` calculations.
- **Zone Heatmaps:** Visual representations of dwell times and store traffic.
- **Anomaly Detection:** Automated alerts for overcrowding, loitering, and group entries.
- **Interactive Dashboard:** Complete UI for video uploads, funnel metrics, and POS data integration.

---

## 🏗️ Architecture Diagrams

### Detection & Event Flow
```
[ CCTV Video Upload ]
            │
            ▼
┌──────────────────────────────────────┐
│       Perception Layer (AI)          │
│  - YOLOv8 Person Detection           │
│  - ByteTrack Multi-Object Tracking   │
└──────────────────┬───────────────────┘
                   │ Bounding boxes + Stable Track IDs
                   ▼
┌──────────────────────────────────────┐
│       Reasoning & Event Engine       │
│  - Excel-Mapped Store Zone Manager   │
│  - Line Crossing Deduplication       │
│  - Heuristic Anomaly Rules           │
└──────────────────┬───────────────────┘
                   │ Structured StoreEvent Data
                   ▼
        [ PostgreSQL 16 DB ]
```

### API & Dashboard Flow
```
        [ PostgreSQL 16 DB ]
                   │
                   ▼
┌──────────────────────────────────────┐
│           FastAPI Server             │
│  - REST Endpoints                    │
│  - Metric Aggregation                │
└──────────────────┬───────────────────┘
                   │ JSON Responses
                   ▼
┌──────────────────────────────────────┐
│      Streamlit Dashboard UI          │
│  - Live Video & Real-Time KPIs       │
│  - Interactive Heatmaps & Funnels    │
└──────────────────────────────────────┘
```

---

## 🚀 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/zairakhaan786/Store-Intelligence-System-for-a-retail-CCTV-analytics-
   cd "Store Intelligence System for a retail CCTV analytics challenge"
   ```

2. **Start the system via Docker Compose:**
   ```bash
   docker compose up --build
   ```

*(Docker will automatically initialize the PostgreSQL database, Redis cache, FastAPI backend, and Streamlit frontend.)*

---

## 🌐 How to Run the Backend

The backend exposes a highly documented OpenAPI Swagger interface. 
Once Docker is running, access the API docs at:
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

---

## 📊 How to Run the Dashboard

The interactive Streamlit dashboard runs automatically with Docker.
Access the live dashboard at:
👉 **[http://localhost:8501](http://localhost:8501)**

---

## 🎥 How to Upload Video

To process a new CCTV video feed:
1. Open the dashboard at `http://localhost:8501`.
2. Locate the **"Upload CCTV Video"** section in the left sidebar.
3. Select your local video file (supported formats: `.mp4`, `.avi`, `.mov`).
4. Click **"Process Video"**. 
5. The system will truncate stale data, pipe the video into the `video_pipeline`, draw bounding boxes, compute analytics, and begin streaming live metrics. 

---

## 🧪 How to Test APIs

You can test the APIs directly via `curl` or through the interactive docs (`http://localhost:8000/docs`).

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Validates API, DB, and system uptime, including feed latency. |
| `POST /events/ingest` | Ingests tracker events matching the exact evaluation schema. |
| `GET /stores/{id}/metrics` | Returns store KPIs: unique visitors, conversion rate, queue depth. |
| `GET /stores/{id}/funnel` | Returns conversion funnel stages deduplicated by session. |
| `GET /stores/{id}/heatmap` | Returns zone visit frequency and dwell heatmaps. |
| `GET /stores/{id}/anomalies` | Returns active operational anomalies (overcrowding, queues). |

**Example:**
```bash
curl -X GET "http://localhost:8000/stores/STORE_BLR_002/metrics" -H "accept: application/json"
```

---

## 📸 Screenshots & Visuals

*(Note: Replace with relative image paths after capturing actual screenshots of your running platform)*
- **Dashboard Overview:** `docs/dashboard_overview.png`
- **Heatmap & Zones:** `docs/heatmap.png`
- **Live Detections:** `docs/detections.png`
- **API Swagger:** `docs/swagger_api.png`

---

## 🛠️ Troubleshooting

- **Docker Port Conflicts:** If ports 8000 or 8501 are in use, modify the `docker-compose.yml` mappings (e.g. `8080:8000`).
- **Dependencies (Local Run):** If running locally without docker, ensure you use `python -m venv venv` and install both `requirements/api.txt` and `requirements/pipeline.txt`.
- **GPU/CPU Fallback:** YOLOv8 defaults to MPS on Mac and CUDA on Nvidia devices. If you experience crashes on older Macs, force CPU mode by editing `src/pipeline/detector.py` to use `device="cpu"`.
- **Database Connection Issues:** Ensure PostgreSQL is fully booted. The FastAPI server uses retry logic, but you can manually check health via `http://localhost:8000/health`.

---
*Built for the Retail AI Challenge | Production Grade Analytics*
