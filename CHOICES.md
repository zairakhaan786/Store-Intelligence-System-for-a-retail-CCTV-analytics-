# Technical Choices & Rationale

## 1. Detection Model Selection (YOLOv8 + ByteTrack)
* **Options Considered:** YOLOv8, RT-DETR, and MediaPipe for detection. DeepSORT, StrongSORT, and ByteTrack for tracking.
* **What AI Suggested:** I used an LLM to compare YOLOv8 and RT-DETR for edge inference. The AI suggested RT-DETR for higher absolute accuracy in complex retail occlusions. For tracking, the AI strongly recommended ByteTrack over DeepSORT because ByteTrack leverages low-confidence bounding boxes to maintain identity across occlusions.
* **What I Chose and Why:** I chose **YOLOv8** instead of RT-DETR because it offers significantly faster FPS on CPU-bound environments while maintaining sufficient accuracy for bounding box tracking. However, I agreed with the AI's recommendation for **ByteTrack**. In busy store aisles, partial occlusions are incredibly common. DeepSORT drops low-confidence boxes which inflates the `unique_visitors` metric as tracking IDs are reset. ByteTrack seamlessly associates these low-confidence boxes, dramatically reducing duplicate counting.

## 2. Event Schema Design Rationale
* **Options Considered:** A highly normalized relational database schema (separate tables for sessions, locations, and events) vs a flattened, wide event stream schema.
* **What AI Suggested:** The AI suggested a deeply nested JSON schema where each visitor had a master object containing an array of all their chronological events, which would make fetching a single user's timeline very fast. 
* **What I Chose and Why:** I overrode the AI's suggestion and chose a **flattened, wide event stream schema** (where each action is an individual JSON event payload: `{"event_type": "ZONE_DWELL", "visitor_id": "VIS_123"}`). A flattened stream is far superior for telemetry ingestion (`POST /events/ingest`) because it allows real-time asynchronous batching without needing to read-modify-write nested user documents. It matches the expected log-style schema of Kafka/Kinesis if this were scaled.

## 3. API Architecture (FastAPI + SQLite)
* **Options Considered:** Flask, Django, and FastAPI. PostgreSQL vs SQLite for the database.
* **What AI Suggested:** The AI recommended Django for its robust built-in ORM and Admin panel, arguing it would be easier to manage the store configurations. For the database, it strongly suggested PostgreSQL to handle concurrent reads/writes from the video pipeline.
* **What I Chose and Why:** I chose **FastAPI** instead of Django. Real-time telemetry ingestion requires high concurrency, and FastAPI's native `asyncio` handles thousands of non-blocking I/O operations better than Django. Furthermore, its Pydantic integration guarantees strict event schema validation. For the database, I chose **SQLite** instead of PostgreSQL. While PostgreSQL is better for production, the grading constraint required the project to run immediately out-of-the-box via `docker compose up`. SQLite requires zero external dependencies, making it portable for immediate evaluation, while SQLAlchemy ensures we can seamlessly switch to PostgreSQL later.
