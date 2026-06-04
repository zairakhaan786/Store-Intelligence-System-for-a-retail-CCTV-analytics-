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
    if "sqlite" in url:
        import sqlite3
        db_path = url.replace("sqlite:///", "").replace("sqlite://", "")
        if not db_path:
            db_path = "store_intelligence.db"
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            sqlite_rows = []
            for r in rows:
                sqlite_rows.append((
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5].isoformat() if isinstance(r[5], datetime) else r[5],
                    r[6],
                    r[7]
                ))
            cursor.executemany(
                """
                INSERT OR IGNORE INTO events (id, event_type, track_id, camera_id, zone_id, timestamp, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                sqlite_rows,
            )
            conn.commit()
            logger.info("CSV ingested (sqlite)", rows=len(rows))
        finally:
            conn.close()
    else:
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




def ingest_sales_csv(csv_path: str, db_url: str | None = None) -> int:
    """
    Ingest a sales transactions CSV into the transactions table.
    Works for both SQLite and PostgreSQL.
    """
    import pandas as pd
    from sqlalchemy import create_engine
    
    url = db_url or settings.database_url
    logger.info("Ingesting sales CSV", path=csv_path, db=url.split("@")[-1])
    
    # Load with pandas for easy handling of column conversions
    df = pd.read_csv(csv_path)
    
    # Select columns that exist in the database model
    cols_mapping = {
        "order_id": "order_id",
        "coupon_code": "coupon_code",
        "offer_name": "offer_name",
        "invoice_number": "invoice_number",
        "order_date": "order_date",
        "order_time": "order_time",
        "store_id": "store_id",
        "store_name": "store_name",
        "customer_name": "customer_name",
        "customer_number": "customer_number",
        "sku": "sku",
        "product_name": "product_name",
        "brand_name": "brand_name",
        "dep_name": "dep_name",
        "sub_category": "sub_category",
        "qty": "qty",
        "GMV": "gmv",
        "NMV": "nmv",
        "total_amount": "total_amount",
        "salesperson_name": "salesperson_name"
    }
    
    # Filter columns that are present in the CSV
    available_cols = {csv_col: db_col for csv_col, db_col in cols_mapping.items() if csv_col in df.columns}
    df_filtered = df[list(available_cols.keys())].rename(columns=available_cols)
    
    # Clean string columns
    for col in ["order_id", "coupon_code", "offer_name", "invoice_number", "order_date", "order_time", 
                "store_id", "store_name", "customer_name", "customer_number", "sku", "product_name", 
                "brand_name", "dep_name", "sub_category", "salesperson_name"]:
        if col in df_filtered.columns:
            df_filtered[col] = df_filtered[col].astype(str).str.strip().replace("nan", None)
            
    # Clean numeric columns
    for col in ["qty"]:
        if col in df_filtered.columns:
            df_filtered[col] = pd.to_numeric(df_filtered[col], errors="coerce").fillna(1).astype(int)
            
    for col in ["gmv", "nmv", "total_amount"]:
        if col in df_filtered.columns:
            df_filtered[col] = pd.to_numeric(df_filtered[col], errors="coerce").fillna(0.0).astype(float)
            
    # Write to database using SQLAlchemy
    engine = create_engine(url)
    
    # SAFE: Check if table exists before querying
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if "order_id" in df_filtered.columns and inspector.has_table("transactions"):
        try:
            existing_orders = pd.read_sql("SELECT order_id FROM transactions", engine)
            existing_order_ids = set(existing_orders["order_id"])
            if existing_order_ids:
                df_filtered = df_filtered[~df_filtered["order_id"].isin(existing_order_ids)]
                logger.info("Filtered existing duplicate orders", remaining_rows=len(df_filtered))
        except Exception as e:
            # Table might not exist yet, that's fine
            pass

    if len(df_filtered) > 0:
        df_filtered.to_sql("transactions", con=engine, if_exists="append", index=False)
    
    logger.info("Sales CSV ingested successfully", rows=len(df_filtered))
    return len(df_filtered)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest CCTV events from CSV")
    parser.add_argument("--csv", help="Path to CCTV event CSV file")
    args = parser.parse_args()

    if args.csv:
        count = ingest_csv(args.csv)
        print(f"Ingested {count} events from CSV")
    else:
        print("Use --csv <path>")
        sys.exit(1)
