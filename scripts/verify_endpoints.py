import sys
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Setup in-memory SQLite database
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Create minimal schema
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            track_id TEXT,
            session_id TEXT,
            camera_id TEXT,
            zone_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            frame_number INTEGER,
            confidence REAL,
            bbox TEXT,
            metadata TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            track_id TEXT NOT NULL,
            session_index INTEGER DEFAULT 0,
            entry_time DATETIME,
            exit_time DATETIME,
            duration_seconds REAL,
            camera_id TEXT,
            entry_zone TEXT,
            exit_zone TEXT,
            zones_visited TEXT DEFAULT '[]',
            is_staff INTEGER DEFAULT 0,
            is_complete INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS anomalies (
            id TEXT PRIMARY KEY,
            anomaly_type TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            zone_id TEXT,
            track_id TEXT,
            description TEXT,
            metadata TEXT DEFAULT '{}',
            detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME,
            is_active INTEGER DEFAULT 1
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS zones (
            id INTEGER PRIMARY KEY,
            zone_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            zone_type TEXT NOT NULL,
            camera_id TEXT,
            polygon TEXT,
            capacity INTEGER DEFAULT 20,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        INSERT OR IGNORE INTO zones (zone_id, name, zone_type, camera_id, capacity)
        VALUES
            ('ENTRY_MAIN', 'Main Entrance', 'entry', 'CAM_01', 10),
            ('AISLE_A', 'Aisle A - Skincare', 'aisle', 'CAM_02', 15),
            ('AISLE_B', 'Aisle B - Makeup', 'aisle', 'CAM_03', 15),
            ('BEAUTY_BAR', 'Beauty Bar', 'beauty_bar', 'CAM_04', 8),
            ('CHECKOUT', 'Checkout Counter', 'checkout', 'CAM_05', 6),
            ('EXIT_MAIN', 'Main Exit', 'exit', 'CAM_01', 10)
    """))
    conn.commit()

# Create transactional SessionLocal
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = SessionLocal()

# Seed database with sample events
import uuid
from datetime import datetime, timezone
import json as json_lib

events = [
    {
        "id": str(uuid.uuid4()), "event_type": "entry", "track_id": "TRACK_1", "session_id": str(uuid.uuid4()),
        "camera_id": "CAM_01", "zone_id": "ENTRY_MAIN", "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "confidence": 0.87, "metadata": json_lib.dumps({}), "session_id": str(uuid.uuid4())
    },
    {
        "id": str(uuid.uuid4()), "event_type": "zone_enter", "track_id": "TRACK_1", "session_id": str(uuid.uuid4()),
        "camera_id": "CAM_02", "zone_id": "AISLE_A", "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "confidence": 0.92, "metadata": json_lib.dumps({}), "session_id": str(uuid.uuid4())
    },
    {
        "id": str(uuid.uuid4()), "event_type": "exit", "track_id": "TRACK_1", "session_id": str(uuid.uuid4()),
        "camera_id": "CAM_01", "zone_id": "EXIT_MAIN", "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "confidence": 0.79, "metadata": json_lib.dumps({}), "session_id": str(uuid.uuid4())
    },
    {
        "id": str(uuid.uuid4()), "event_type": "reentry", "track_id": "TRACK_1", "session_id": None,
        "camera_id": "CAM_01", "zone_id": "ENTRY_MAIN", "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "confidence": 0.85, "metadata": json_lib.dumps({"session_index": 1}), "session_id": None
    },
    {
        "id": str(uuid.uuid4()), "event_type": "group_entry", "track_id": "GROUP", "session_id": None,
        "camera_id": "CAM_01", "zone_id": "ENTRY_MAIN", "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "confidence": 1.0, "metadata": json_lib.dumps({"group_size": 4}), "session_id": None
    },
    {
        "id": str(uuid.uuid4()), "event_type": "anomaly", "track_id": "TRACK_7", "session_id": None,
        "camera_id": "CAM_01", "zone_id": "ENTRY_MAIN", "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "confidence": 0.9, "metadata": json_lib.dumps({"anomaly_type": "loitering", "severity": "medium"}), "session_id": None
    }
]

for ev in events:
    db_session.execute(
        text("""
            INSERT OR IGNORE INTO events (id, event_type, track_id, session_id, camera_id, zone_id, timestamp, confidence, metadata)
            VALUES (:id, :event_type, :track_id, :session_id, :camera_id, :zone_id, :timestamp, :confidence, :metadata)
        """),
        ev,
    )
db_session.commit()

# Override get_db in FastAPI
from src.api.main import app
from src.api.models.database import get_db

def _override_get_db():
    try:
        yield db_session
    finally:
        pass

app.dependency_overrides[get_db] = _override_get_db

# Create TestClient and request endpoints
client = TestClient(app)

endpoints = [
    "/health",
    "/metrics",
    "/metrics/funnel",
    "/metrics/occupancy",
    "/metrics/heatmap",
    "/events?page=1&page_size=2",
    "/anomalies"
]

print("=== VERIFYING ENDPOINTS FUNCTIONALITY ===")
for path in endpoints:
    print(f"\nRequesting: GET {path}")
    resp = client.get(path)
    print(f"Status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))

db_session.close()
