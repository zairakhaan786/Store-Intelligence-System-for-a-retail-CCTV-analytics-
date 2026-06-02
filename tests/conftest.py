"""
Pytest configuration and shared fixtures.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Override DB URL for tests — use SQLite in-memory
TEST_DB_URL = "sqlite:///:memory:"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["POSTGRES_DB"] = "store_intelligence_test"
os.environ["POSTGRES_USER"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test"

from src.api.models.database import Base, EventModel, SessionModel, AnomalyModel
from src.api.models.database import get_db
from src.api.main import app
from src.shared.config import settings


@pytest.fixture(scope="session")
def sqlite_engine():
    """SQLite engine for unit tests (no Docker needed)."""
    from sqlalchemy import Column, DateTime, Float, Integer, String, Boolean, JSON
    from sqlalchemy.orm import DeclarativeBase

    from sqlalchemy.pool import StaticPool
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create minimal schema for SQLite tests
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
                ('AISLE_A', 'Aisle A', 'aisle', 'CAM_02', 15),
                ('CHECKOUT', 'Checkout', 'checkout', 'CAM_05', 6),
                ('EXIT_MAIN', 'Exit', 'exit', 'CAM_01', 10)
        """))
        conn.commit()

    return engine


@pytest.fixture
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """Return a transactional test DB session that rolls back after each test."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def api_client(db_session: Session) -> Generator:
    """FastAPI test client with DB dependency override."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_events(db_session: Session) -> list:
    """Insert sample events into test DB."""
    import json
    events = [
        {
            "id": str(uuid.uuid4()),
            "event_type": "entry",
            "track_id": "TRACK_1",
            "session_id": str(uuid.uuid4()),
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "confidence": 0.87,
            "metadata": json.dumps({}),
        },
        {
            "id": str(uuid.uuid4()),
            "event_type": "zone_enter",
            "track_id": "TRACK_1",
            "session_id": str(uuid.uuid4()),
            "camera_id": "CAM_02",
            "zone_id": "AISLE_A",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "confidence": 0.92,
            "metadata": json.dumps({}),
        },
        {
            "id": str(uuid.uuid4()),
            "event_type": "exit",
            "track_id": "TRACK_1",
            "session_id": str(uuid.uuid4()),
            "camera_id": "CAM_01",
            "zone_id": "EXIT_MAIN",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "confidence": 0.79,
            "metadata": json.dumps({}),
        },
        {
            "id": str(uuid.uuid4()),
            "event_type": "reentry",
            "track_id": "TRACK_1",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "confidence": 0.85,
            "metadata": json.dumps({"session_index": 1}),
        },
        {
            "id": str(uuid.uuid4()),
            "event_type": "group_entry",
            "track_id": "GROUP",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "confidence": 1.0,
            "metadata": json.dumps({"group_size": 4}),
        },
        {
            "id": str(uuid.uuid4()),
            "event_type": "anomaly",
            "track_id": "TRACK_7",
            "camera_id": "CAM_01",
            "zone_id": "ENTRY_MAIN",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "confidence": 0.9,
            "metadata": json.dumps({"anomaly_type": "loitering", "severity": "medium"}),
        },
    ]
    for ev in events:
        ev.setdefault("session_id", None)
        db_session.execute(
            text("""
                INSERT OR IGNORE INTO events (id, event_type, track_id, session_id, camera_id, zone_id, timestamp, confidence, metadata)
                VALUES (:id, :event_type, :track_id, :session_id, :camera_id, :zone_id, :timestamp, :confidence, :metadata)
            """),
            ev,
        )
    db_session.commit()
    return events
