# System Design Document

## Objective
To build an end-to-end AI Store Intelligence System capable of analyzing retail CCTV footage in real-time to extract actionable business metrics, including footfall, dwell time, zone heatmaps, and conversion rates.

## Core Modules

### 1. Detection & Tracking Module
*   **Model:** YOLOv8n (Nano variant chosen for CPU/Edge processing speed).
*   **Tracker:** ByteTrack.
*   **Logic:** Defines spatial polygons representing store zones (`ENTRY_MAIN`, `CHECKOUT`, `AISLE_A`). Uses `shapely` for Point-in-Polygon calculations to determine when a tracked bounding box centroid enters a specific zone.

### 2. Event Ingestion System
*   A REST API endpoint (`POST /events/ingest`) accepts telemetry.
*   **Event Schema:** Requires `store_id`, `camera_id`, `visitor_id` (Track ID), `event_type` (entry, exit, zone_enter), and `timestamp`.

### 3. Session Management Engine
*   Converts raw point-in-time events into continuous "Visitor Sessions".
*   Maintains state such as `entry_time`, `exit_time`, and a list of visited zones.
*   Calculates `dwell_time` upon exit or upon transitioning between zones.

### 4. Anomaly Detection Engine
*   Runs asynchronously alongside the API.
*   Monitors active sessions against predefined thresholds:
    *   **Overcrowding:** Triggers if total active visitors > capacity threshold.
    *   **Queue Depth:** Triggers if `CHECKOUT` zone occupancy > queue threshold.

### 5. Funnel Analytics Engine
*   Aggregates session data to build a standard retail conversion funnel:
    1.  **Walk-ins:** Total unique sessions.
    2.  **Browsing:** Sessions that entered product aisles.
    3.  **Checkout Queue:** Sessions that entered the checkout zone.
    4.  **Conversion:** Extracted by combining CCTV checkout presence with POS (Point of Sale) transaction data.

## AI-Assisted Decisions

1. **Choosing the Object Tracking Strategy:** I initially considered using DeepSORT for tracking. I queried an LLM to compare DeepSORT and ByteTrack for crowded retail scenarios. The LLM advised that ByteTrack retains low-confidence bounding boxes to associate track IDs across partial occlusions, which is vital for busy aisles. I agreed with this suggestion and adopted ByteTrack, which greatly reduced duplicate counting.
2. **Handling SQL Complexity in Funnel Extraction:** I asked an LLM to help me design the SQL aggregation query that correlates Point-of-Sale (POS) transactions with CCTV checkout dwell events. The LLM suggested doing the entire correlation natively inside SQLite using an extensive JOIN. I overrode this suggestion because SQLite's timestamp handling is inconsistent, and I opted to fetch events into Python and process the correlation in the application layer for better cross-dialect safety.
3. **Structuring the REST API:** I used an LLM to structure the Pydantic schemas (`EventOut`, `MetricsResponse`). The LLM suggested nesting all metadata tightly into custom classes. I modified this to use `Dict[str, Any]` for `metadata` to remain highly flexible for arbitrary JSON fields injected by different pipeline steps.
