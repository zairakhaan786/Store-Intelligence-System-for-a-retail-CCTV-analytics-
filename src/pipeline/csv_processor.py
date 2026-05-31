"""
CSV Event Processor — ingests the provided CCTV event CSV into PostgreSQL.

The CSV is expected to have columns such as:
  timestamp, track_id, event_type, zone_id, camera_id, confidence, bbox_x1, bbox_y1, bbox_x2, bbox_y2, metadata

If column names differ, we do a best-effort column mapping.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import psycopg2
from psycopg2.extras import execute_values

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

# Column name aliases for flexible CSV ingestion
COLUMN_ALIASES = {
    "timestamp": ["timestamp", "time", "datetime", "event_time", "ts"],
    "track_id": ["track_id", "trackid", "person_id", "id", "track"],
    "event_type": ["event_type", "type", "event", "action"],
    "zone_id": ["zone_id", "zone", "location", "area"],
    "camera_id": ["camera_id", "camera", "cam_id", "cam"],
    "confidence": ["confidence", "conf", "score"],
}


def _resolve_column(headers: List[str], canonical: str) -> str | None:
    """Find the actual column name from a list of aliases."""
    aliases = COLUMN_ALIASES.get(canonical, [canonical])
    h_lower = {h.lower(): h for h in headers}
    for alias in aliases:
        if alias.lower() in h_lower:
            return h_lower[alias.lower()]
    return None


def _parse_timestamp(val: str) -> datetime:
    """Parse various timestamp formats."""
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(val.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {val!r}")


def ingest_csv(csv_path: str, db_url: str | None = None) -> int:
    """
    Ingest a CCTV event CSV file into the PostgreSQL events table.

    Returns:
        Number of rows inserted
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    url = db_url or settings.database_url
    rows: List[tuple] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        logger.info("CSV headers detected", headers=headers)

        # Resolve columns
        col_ts = _resolve_column(headers, "timestamp")
        col_tid = _resolve_column(headers, "track_id")
        col_ev = _resolve_column(headers, "event_type")
        col_zone = _resolve_column(headers, "zone_id")
        col_cam = _resolve_column(headers, "camera_id")
        col_conf = _resolve_column(headers, "confidence")

        for row_num, row in enumerate(reader, start=2):
            try:
                ts = _parse_timestamp(row[col_ts]) if col_ts else datetime.now(tz=timezone.utc)
                track_id = row.get(col_tid, f"TRACK_{row_num}") if col_tid else f"TRACK_{row_num}"
                event_type = row.get(col_ev, "entry").strip().lower() if col_ev else "entry"
                zone_id = row.get(col_zone, "ENTRY_MAIN").strip() if col_zone else "ENTRY_MAIN"
                camera_id = row.get(col_cam, "CAM_01").strip() if col_cam else "CAM_01"
                confidence = float(row.get(col_conf, 1.0)) if col_conf else 1.0

                # Build metadata from remaining columns
                meta_keys = [
                    k for k in row.keys()
                    if k not in [col_ts, col_tid, col_ev, col_zone, col_cam, col_conf]
                ]
                metadata = {k: row[k] for k in meta_keys if row.get(k)}

                rows.append((
                    str(uuid.uuid4()),  # id
                    event_type,
                    str(track_id),
                    camera_id,
                    zone_id,
                    ts,
                    confidence,
                    json.dumps(metadata),
                ))
            except Exception as exc:
                logger.warning(f"Skipping row {row_num}: {exc}")
                continue

    if not rows:
        logger.warning("No valid rows found in CSV")
        return 0

    # Insert into DB
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO events (id, event_type, track_id, camera_id, zone_id, timestamp, confidence, metadata)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                rows,
            )
        conn.commit()
        logger.info("CSV ingested", rows=len(rows))
    finally:
        conn.close()

    return len(rows)


def generate_synthetic_events(db_url: str | None = None, n_visitors: int = 50) -> int:
    """
    Generate synthetic event data for demonstration when no CSV is provided.
    Simulates a realistic retail day with entries, zone visits, and exits.
    """
    import random
    from datetime import timedelta

    url = db_url or settings.database_url
    base_time = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    events = []
    sessions = []

    zone_sequence = [
        ["ENTRY_MAIN", "AISLE_A", "BEAUTY_BAR", "CHECKOUT", "EXIT_MAIN"],
        ["ENTRY_MAIN", "AISLE_B", "CHECKOUT", "EXIT_MAIN"],
        ["ENTRY_MAIN", "AISLE_A", "AISLE_B", "EXIT_MAIN"],
        ["ENTRY_MAIN", "BEAUTY_BAR", "EXIT_MAIN"],
        ["ENTRY_MAIN", "CHECKOUT", "EXIT_MAIN"],
        ["ENTRY_MAIN", "EXIT_MAIN"],  # quick exit
    ]

    staff_ids = [9901, 9902, 9903]

    for visitor_num in range(n_visitors):
        track_id = visitor_num + 1
        is_staff = track_id in staff_ids
        session_id = str(uuid.uuid4())

        # Random entry time spread across store hours (9am–9pm)
        entry_offset = random.randint(0, 43200)  # 12 hours
        entry_time = base_time + timedelta(seconds=entry_offset)

        # Random visitor journey
        journey = random.choice(zone_sequence)
        current_time = entry_time
        zones_visited = []

        for zone_id in journey:
            event_type = "entry" if zone_id == journey[0] else (
                "exit" if zone_id == journey[-1] else "zone_enter"
            )
            if zone_id == journey[0] and random.random() < 0.08:
                event_type = "reentry"  # 8% chance of re-entry

            events.append((
                str(uuid.uuid4()),
                event_type,
                str(track_id),
                session_id,
                "CAM_01",
                zone_id,
                current_time,
                None,  # frame_number
                round(random.uniform(0.65, 0.98), 3),  # confidence
                json.dumps({"bbox": {"x1": 0.2, "y1": 0.3, "x2": 0.4, "y2": 0.9}}),
                json.dumps({"is_staff": is_staff, "session_index": 0}),
            ))
            zones_visited.append(zone_id)

            # Dwell time per zone
            if event_type not in ("exit",):
                dwell = random.randint(30, 600)
                current_time += timedelta(seconds=dwell)

        exit_time = current_time
        duration = (exit_time - entry_time).total_seconds()

        sessions.append((
            session_id,
            str(track_id),
            0,
            entry_time,
            exit_time,
            round(duration, 2),
            "CAM_01",
            journey[0],
            journey[-1],
            json.dumps(zones_visited),
            is_staff,
            True,
            json.dumps({}),
        ))

    # Add some group entry events
    group_time = base_time + timedelta(hours=2)
    for g in range(3):
        events.append((
            str(uuid.uuid4()),
            "group_entry",
            "GROUP",
            None,
            "CAM_01",
            "ENTRY_MAIN",
            group_time + timedelta(minutes=g * 45),
            None,
            1.0,
            json.dumps({}),
            json.dumps({"group_size": random.randint(3, 5)}),
        ))

    # Add anomaly events
    events.append((
        str(uuid.uuid4()),
        "anomaly",
        "TRACK_7",
        None,
        "CAM_01",
        "ENTRY_MAIN",
        base_time + timedelta(hours=3),
        None,
        0.9,
        json.dumps({}),
        json.dumps({"anomaly_type": "loitering", "severity": "medium", "dwell_seconds": 150}),
    ))

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            # Insert events
            execute_values(
                cur,
                """
                INSERT INTO events (id, event_type, track_id, session_id, camera_id, zone_id,
                    timestamp, frame_number, confidence, bbox, metadata)
                VALUES %s ON CONFLICT DO NOTHING
                """,
                events,
            )
            # Insert sessions
            execute_values(
                cur,
                """
                INSERT INTO sessions (id, track_id, session_index, entry_time, exit_time,
                    duration_seconds, camera_id, entry_zone, exit_zone, zones_visited,
                    is_staff, is_complete, metadata)
                VALUES %s ON CONFLICT DO NOTHING
                """,
                sessions,
            )
        conn.commit()
        logger.info("Synthetic data generated", events=len(events), sessions=len(sessions))
    finally:
        conn.close()

    return len(events)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest CCTV events from CSV")
    parser.add_argument("--csv", help="Path to CCTV event CSV file")
    parser.add_argument("--synthetic", action="store_true", help="Generate synthetic data")
    parser.add_argument("--visitors", type=int, default=50, help="Number of synthetic visitors")
    args = parser.parse_args()

    if args.csv:
        count = ingest_csv(args.csv)
        print(f"Ingested {count} events from CSV")
    elif args.synthetic:
        count = generate_synthetic_events(n_visitors=args.visitors)
        print(f"Generated {count} synthetic events")
    else:
        print("Use --csv <path> or --synthetic")
        sys.exit(1)
