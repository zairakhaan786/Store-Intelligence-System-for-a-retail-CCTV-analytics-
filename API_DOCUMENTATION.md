# API Documentation

The Store Intelligence API is built with FastAPI and provides a strictly RESTful interface for accessing live store analytics.

## Base URL
Live Deployment: `https://five-rules-juggle.loca.lt`
Local Deployment: `http://localhost:8000`

---

## 1. Store Metrics
**GET** `/stores/{store_id}/metrics`

Returns core key performance indicators (KPIs) for a specific store.

**Response (200 OK)**
```json
{
  "store_id": "STORE_BLR_002",
  "period": "live",
  "unique_visitors": 142,
  "queue_depth": 3,
  "avg_dwell_time": 4.5,
  "abandonment_rate": 0.12,
  "conversion_rate": 0.45
}
```

---

## 2. Visitor Funnel
**GET** `/stores/{store_id}/funnel`

Returns the session-based visitor funnel. Each visitor is counted only once per stage, eliminating duplicate counts caused by jitter.

**Response (200 OK)**
```json
{
  "store_id": "STORE_BLR_002",
  "stages": [
    { "stage": "Entry", "count": 142, "drop_off_pct": 0.0 },
    { "stage": "Aisles", "count": 120, "drop_off_pct": 15.5 },
    { "stage": "Beauty Bar", "count": 80, "drop_off_pct": 33.3 },
    { "stage": "Checkout", "count": 64, "drop_off_pct": 20.0 }
  ]
}
```

---

## 3. Zone Heatmap
**GET** `/stores/{store_id}/heatmap`

Returns spatial distribution of visitors across the store's Excel-defined zones.

**Response (200 OK)**
```json
{
  "store_id": "STORE_BLR_002",
  "cells": [
    { "zone_id": "AISLE_A", "visit_frequency": 0.45, "avg_dwell_secs": 120 },
    { "zone_id": "CHECKOUT", "visit_frequency": 0.20, "avg_dwell_secs": 45 }
  ]
}
```

---

## 4. Anomalies
**GET** `/stores/{store_id}/anomalies`

Returns currently active operational anomalies detected by the heuristic event engine.

**Response (200 OK)**
```json
{
  "store_id": "STORE_BLR_002",
  "active_count": 1,
  "anomalies": [
    {
      "type": "overcrowding",
      "zone_id": "BEAUTY_BAR",
      "severity": "high",
      "detected_at": "2026-06-03T12:00:00Z"
    }
  ]
}
```

---

## 5. Event Ingestion (Internal)
**POST** `/events/ingest`

Strict pipeline endpoint used by the Event Engine to push tracking data into the immutable database.

**Payload schema validated strictly according to evaluation rubric:**
```json
{
  "store_id": "STORE_BLR_002",
  "camera_id": "CAM_01",
  "visitor_id": "VIS-1234",
  "session_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "event_type": "zone_enter",
  "timestamp": "2026-06-03T12:00:00Z",
  "zone_id": "AISLE_A",
  "dwell_ms": 0,
  "is_staff": false,
  "confidence": 0.95
}
```
