# Technical Choices & Rationale

## 1. Why FastAPI?
We chose **FastAPI** over Flask or Django for the backend because:
*   **Asynchronous by Default:** The perception pipeline sends a high volume of telemetry events (entries, exits, zone changes). FastAPI's `asyncio` support allows it to handle thousands of concurrent I/O operations without blocking.
*   **Pydantic Validation:** Real-time AI pipelines can occasionally produce noisy or malformed data. FastAPI's native integration with Pydantic ensures strict schema validation at the ingestion endpoint.
*   **Auto-generated Docs:** Out-of-the-box Swagger UI (OpenAPI) is critical for enterprise submissions and integrations.

## 2. Why YOLOv8 + ByteTrack?
*   **YOLOv8 (Ultralytics):** Represents the current state-of-the-art in real-time object detection. It provides the perfect balance between inference speed and accuracy, crucial for processing 30 FPS video streams.
*   **ByteTrack:** Traditional trackers drop track IDs when confidence scores dip (e.g., partial occlusions). ByteTrack associates almost every detection box instead of only high-score ones, significantly reducing ID switching and preventing duplicate counting of the same visitor.

## 3. Why Streamlit for the Dashboard?
*   **Rapid Iteration:** Streamlit allows for building Python-native dashboards in hours rather than weeks.
*   **Customization:** By injecting custom CSS and HTML, we transformed Streamlit's standard UI into a highly polished, neon-aesthetic production-ready interface.
*   **State Management:** Easily manages polling and caching for live dashboard updates.

## 4. Why SQLite for Demonstration?
*   **Portability:** The repository is designed for immediate evaluation by reviewers. SQLite requires zero external dependencies, allowing `docker compose up` to work seamlessly without complex PostgreSQL configuration.
*   **Scalability Path:** The database layer uses SQLAlchemy ORM, meaning transitioning from SQLite to PostgreSQL in a true production environment requires only changing the `DATABASE_URL` string.

## 5. Overcoming Duplicate Counting
A major challenge in CCTV analytics is a single person being counted twice due to occlusions. We solved this by:
1. Using **ByteTrack** for resilient ID preservation across frames.
2. Implementing **Sessionization** in the API layer. Even if the tracking ID switches, the spatial logic ensures that entry lines cannot be crossed backwards without triggering an exit, allowing us to reconcile sessions and discard duplicate entry events within a short time window.
