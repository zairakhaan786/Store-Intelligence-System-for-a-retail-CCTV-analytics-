"""
SQLAlchemy database models for the Store Intelligence System.
Mirrors the SQL schema in db/init.sql.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    pass


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zone_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    zone_type = Column(String(50), nullable=False)
    camera_id = Column(String(50))
    polygon = Column(JSON)
    capacity = Column(Integer, default=20)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    location = Column(String(200))
    zone_id = Column(String(50))
    resolution = Column(String(20), default="1920x1080")
    fps = Column(Integer, default=25)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    track_id = Column(String(100), nullable=False)
    session_index = Column(Integer, default=0)
    entry_time = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    exit_time = Column(DateTime(timezone=True))
    duration_seconds = Column(Float)
    camera_id = Column(String(50))
    entry_zone = Column(String(50))
    exit_zone = Column(String(50))
    zones_visited = Column(JSON, default=list)
    is_staff = Column(Boolean, default=False)
    is_complete = Column(Boolean, default=False)
    metadata_dict = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class EventModel(Base):
    __tablename__ = "events"

    id = Column("id", String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store_id = Column(String(50), default="STORE_BLR_002")
    camera_id = Column(String(50))
    visitor_id = Column(String(100))
    session_id = Column(String(36))
    event_type = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    zone_id = Column(String(50))
    dwell_ms = Column(Integer, nullable=True)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float)
    metadata_dict = Column("metadata", JSON, default=dict)
    frame_number = Column(Integer)
    bbox = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class OccupancyModel(Base):
    __tablename__ = "occupancy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zone_id = Column(String(50), nullable=False)
    bucket_time = Column(DateTime(timezone=True), nullable=False)
    count = Column(Integer, default=0)
    max_count = Column(Integer, default=0)
    avg_dwell = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (UniqueConstraint("zone_id", "bucket_time", name="uq_occupancy"),)


class AnomalyModel(Base):
    __tablename__ = "anomalies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    anomaly_type = Column(String(100), nullable=False)
    severity = Column(String(20), default="medium")
    zone_id = Column(String(50))
    track_id = Column(String(100))
    description = Column(Text)
    metadata_dict = Column("metadata", JSON, default=dict)
    detected_at = Column(DateTime(timezone=True), default=_utcnow)
    resolved_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)


class MetricsSnapshotModel(Base):
    __tablename__ = "metrics_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime(timezone=True), nullable=False)
    period = Column(String(20), nullable=False)
    total_entries = Column(Integer, default=0)
    total_exits = Column(Integer, default=0)
    unique_visitors = Column(Integer, default=0)
    avg_dwell_secs = Column(Float, default=0.0)
    peak_occupancy = Column(Integer, default=0)
    conversion_rate = Column(Float, default=0.0)
    reentry_count = Column(Integer, default=0)
    group_entry_count = Column(Integer, default=0)
    anomaly_count = Column(Integer, default=0)
    metadata_dict = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

class TransactionModel(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), nullable=False)
    coupon_code = Column(String(100))
    offer_name = Column(String(200))
    invoice_number = Column(String(100))
    order_date = Column(String(20))
    order_time = Column(String(20))
    store_id = Column(String(50))
    store_name = Column(String(100))
    customer_name = Column(String(100))
    customer_number = Column(String(50))
    sku = Column(String(100))
    product_name = Column(String(300))
    brand_name = Column(String(100))
    dep_name = Column(String(100))
    sub_category = Column(String(100))
    qty = Column(Integer, default=1)
    gmv = Column(Float, default=0.0)
    nmv = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    salesperson_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ── Engine + Session Factory ──────────────────────────────────────────────────

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        db_url = settings.database_url
        if db_url.startswith("sqlite"):
            _engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                echo=False,
            )
        else:
            _engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                echo=False,
            )
        # Auto-create all tables
        Base.metadata.create_all(bind=_engine)
        logger.info("Database engine created", url=db_url.split("@")[-1] if "@" in db_url else db_url)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _SessionLocal


def get_db():
    """FastAPI dependency — yields a DB session."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def health_check() -> bool:
    """Returns True if DB connection is healthy."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB health check failed", error=str(exc))
        return False
