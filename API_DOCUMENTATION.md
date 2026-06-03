# API Documentation

The Store Intelligence backend provides a RESTful API built with FastAPI. It handles telemetry ingestion from the AI pipeline, real-time metrics aggregation for the dashboard, and anomaly alerting.

## Base URL
Local Development: `http://localhost:8000`
Live API / Swagger: `https://a0e1c410ae7f04.lhr.life/docs`

---

## 1. Event Ingestion

### `POST /events/ingest`
Ingests a batch of telemetry events from the computer vision pipeline.

**Request Payload (JSON):**
```json
{
  "events": [
    {
      "store_id": "STORE_BLR_002",
      "camera_id": "CAM_01",
      "visitor_id": "VISITOR_0045",
      "event_type": "zone_enter",
      "timestamp": "2023-10-27T10:30:00Z",
      "zone_id": "AISLE_A",
      "is_staff": false,
      "confidence": 0.95
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "processed_count": 1
}
```

---

## 2. Real-Time Metrics

### `GET /stores/{store_id}/metrics`
Retrieves aggregated KPIs for the dashboard overview.

**Response:**
```json
{
  "unique_visitors": 112,
  "conversion_rate": 0.417,
  "avg_dwell_per_zone": {
    "ENTRY_MAIN": 12.5,
    "AISLE_A": 145.2
  },
  "queue_depth": 3,
  "abandonment_rate": 0.12
}
```

---

## 3. Spatial Analytics

### `GET /metrics/occupancy`
Retrieves real-time occupancy counts across all predefined store zones.

**Response:**
```json
{
  "zones": [
    {
      "name": "ENTRY_MAIN",
      "current_count": 8,
      "capacity": 10,
      "utilization_pct": 80.0
    },
    {
      "name": "CHECKOUT",
      "current_count": 3,
      "capacity": 6,
      "utilization_pct": 50.0
    }
  ]
}
```

---

## 4. Visitor Funnel

### `GET /stores/{store_id}/funnel`
Retrieves the session-based visitor funnel for conversion tracking.

**Response:**
```json
{
  "stages": [
    {"stage": "Walk-ins", "count": 127},
    {"stage": "Browsing", "count": 110},
    {"stage": "Checkout", "count": 55},
    {"stage": "Purchase", "count": 53}
  ],
  "conversion_rate": 0.417,
  "avg_stages_per_visitor": 2.5
}
```

---

## 5. System Controls

### `POST /pipeline/upload-video`
Uploads a local CCTV video file and triggers the YOLOv8 + ByteTrack processing pipeline asynchronously.

**Form Data:**
*   `file`: Video file (mp4, avi, mov)

**Response:**
```json
{
  "filename": "cctv_feed.mp4",
  "message": "Video processing pipeline started in background",
  "status": "processing"
}
```
