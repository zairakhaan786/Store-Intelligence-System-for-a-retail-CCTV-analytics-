-- =============================================================
-- Store Intelligence System — PostgreSQL Schema
-- AI Store Intelligence System
-- =============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================
-- ZONES — Store layout zones from Excel
-- =============================================================
CREATE TABLE IF NOT EXISTS zones (
    id          SERIAL PRIMARY KEY,
    zone_id     VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    zone_type   VARCHAR(50) NOT NULL, -- 'entry', 'exit', 'aisle', 'checkout', 'beauty_bar', 'stockroom'
    camera_id   VARCHAR(50),
    polygon     JSONB,          -- [[x1,y1],[x2,y2],...] normalized 0-1
    capacity    INTEGER DEFAULT 20,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- CAMERAS — CCTV camera registry
-- =============================================================
CREATE TABLE IF NOT EXISTS cameras (
    id          SERIAL PRIMARY KEY,
    camera_id   VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    location    VARCHAR(200),
    zone_id     VARCHAR(50) REFERENCES zones(zone_id),
    resolution  VARCHAR(20) DEFAULT '1920x1080',
    fps         INTEGER DEFAULT 25,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- SESSIONS — Per-visitor sessions (deduplication unit)
-- =============================================================
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    track_id        VARCHAR(100) NOT NULL,
    session_index   INTEGER DEFAULT 0,          -- increments on re-entry
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    duration_seconds FLOAT,
    camera_id       VARCHAR(50),
    entry_zone      VARCHAR(50),
    exit_zone       VARCHAR(50),
    zones_visited   JSONB DEFAULT '[]',         -- ordered zone visit list
    is_staff        BOOLEAN DEFAULT FALSE,
    is_complete     BOOLEAN DEFAULT FALSE,      -- False if still in store
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sessions_track_id ON sessions(track_id);
CREATE INDEX idx_sessions_entry_time ON sessions(entry_time);
CREATE INDEX idx_sessions_is_complete ON sessions(is_complete);

-- =============================================================
-- EVENTS — All pipeline events (entry, exit, dwell, anomaly, etc.)
-- =============================================================
CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    store_id        VARCHAR(50) DEFAULT 'STORE_BLR_002',
    camera_id       VARCHAR(50),
    visitor_id      VARCHAR(100),
    session_id      UUID REFERENCES sessions(id) ON DELETE SET NULL,
    event_type      VARCHAR(50) NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    zone_id         VARCHAR(50),
    dwell_ms        INTEGER,
    is_staff        BOOLEAN DEFAULT FALSE,
    confidence      FLOAT,
    metadata        JSONB DEFAULT '{}',
    -- Additional fields not strictly in schema but useful for pipeline
    frame_number    INTEGER,
    bbox            JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_visitor ON events(visitor_id);
CREATE INDEX idx_events_ts ON events(timestamp);
CREATE INDEX idx_events_zone ON events(zone_id);

-- =============================================================
-- OCCUPANCY — Zone occupancy time-series (1-minute buckets)
-- =============================================================
CREATE TABLE IF NOT EXISTS occupancy (
    id          SERIAL PRIMARY KEY,
    zone_id     VARCHAR(50) NOT NULL,
    bucket_time TIMESTAMPTZ NOT NULL,  -- truncated to minute
    count       INTEGER DEFAULT 0,
    max_count   INTEGER DEFAULT 0,
    avg_dwell   FLOAT DEFAULT 0.0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(zone_id, bucket_time)
);

CREATE INDEX idx_occupancy_zone_time ON occupancy(zone_id, bucket_time);

-- =============================================================
-- ANOMALIES — Detected anomaly events
-- =============================================================
CREATE TABLE IF NOT EXISTS anomalies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    anomaly_type    VARCHAR(100) NOT NULL, -- 'overcrowding','long_dwell','unusual_path','loitering','tailgating'
    severity        VARCHAR(20) DEFAULT 'medium', -- 'low','medium','high','critical'
    zone_id         VARCHAR(50),
    track_id        VARCHAR(100),
    description     TEXT,
    metadata        JSONB DEFAULT '{}',
    detected_at     TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_anomalies_type ON anomalies(anomaly_type);
CREATE INDEX idx_anomalies_active ON anomalies(is_active);
CREATE INDEX idx_anomalies_zone ON anomalies(zone_id);

-- =============================================================
-- METRICS_SNAPSHOT — Cached daily/hourly metric rollups
-- =============================================================
CREATE TABLE IF NOT EXISTS metrics_snapshot (
    id              SERIAL PRIMARY KEY,
    snapshot_time   TIMESTAMPTZ NOT NULL,
    period          VARCHAR(20) NOT NULL,  -- 'hourly','daily'
    total_entries   INTEGER DEFAULT 0,
    total_exits     INTEGER DEFAULT 0,
    unique_visitors INTEGER DEFAULT 0,
    avg_dwell_secs  FLOAT DEFAULT 0.0,
    peak_occupancy  INTEGER DEFAULT 0,
    conversion_rate FLOAT DEFAULT 0.0,    -- visitors who reached checkout/beauty zones
    reentry_count   INTEGER DEFAULT 0,
    group_entry_count INTEGER DEFAULT 0,
    anomaly_count   INTEGER DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_time, period)
);

-- =============================================================
-- SEED DATA — Store layout (Retail store with 6 zones)
-- =============================================================
INSERT INTO zones (zone_id, name, zone_type, camera_id, polygon, capacity) VALUES
    ('ENTRY_MAIN',  'Main Entrance',     'entry',      'CAM_01', '[{"x":0.0,"y":0.8},{"x":1.0,"y":0.8},{"x":1.0,"y":1.0},{"x":0.0,"y":1.0}]', 10),
    ('AISLE_A',     'Aisle A - Skincare','aisle',      'CAM_02', '[{"x":0.0,"y":0.5},{"x":0.5,"y":0.5},{"x":0.5,"y":0.8},{"x":0.0,"y":0.8}]', 15),
    ('AISLE_B',     'Aisle B - Makeup',  'aisle',      'CAM_03', '[{"x":0.5,"y":0.5},{"x":1.0,"y":0.5},{"x":1.0,"y":0.8},{"x":0.5,"y":0.8}]', 15),
    ('BEAUTY_BAR',  'Beauty Bar',        'beauty_bar', 'CAM_04', '[{"x":0.2,"y":0.2},{"x":0.8,"y":0.2},{"x":0.8,"y":0.5},{"x":0.2,"y":0.5}]', 8),
    ('CHECKOUT',    'Checkout Counter',  'checkout',   'CAM_05', '[{"x":0.0,"y":0.0},{"x":1.0,"y":0.0},{"x":1.0,"y":0.2},{"x":0.0,"y":0.2}]', 6),
    ('EXIT_MAIN',   'Main Exit',         'exit',       'CAM_01', '[{"x":0.0,"y":0.85},{"x":1.0,"y":0.85},{"x":1.0,"y":1.0},{"x":0.0,"y":1.0}]', 10)
ON CONFLICT (zone_id) DO NOTHING;

INSERT INTO cameras (camera_id, name, location, zone_id, resolution, fps) VALUES
    ('CAM_01', 'Entrance Camera',    'Main Door',       'ENTRY_MAIN', '1920x1080', 25),
    ('CAM_02', 'Aisle A Camera',     'Skincare Aisle',  'AISLE_A',    '1920x1080', 25),
    ('CAM_03', 'Aisle B Camera',     'Makeup Aisle',    'AISLE_B',    '1920x1080', 25),
    ('CAM_04', 'Beauty Bar Camera',  'Beauty Station',  'BEAUTY_BAR', '1920x1080', 25),
    ('CAM_05', 'Checkout Camera',    'POS Counter',     'CHECKOUT',   '1920x1080', 25)
ON CONFLICT (camera_id) DO NOTHING;

-- =============================================================
-- VIEWS — Useful computed views
-- =============================================================
CREATE OR REPLACE VIEW v_active_sessions AS
SELECT
    s.track_id,
    s.entry_time,
    EXTRACT(EPOCH FROM (NOW() - s.entry_time)) AS current_dwell_secs,
    s.entry_zone,
    s.zones_visited,
    s.is_staff
FROM sessions s
WHERE s.is_complete = FALSE;

CREATE OR REPLACE VIEW v_hourly_metrics AS
SELECT
    DATE_TRUNC('hour', e.timestamp) AS hour,
    COUNT(*) FILTER (WHERE e.event_type = 'entry') AS entries,
    COUNT(*) FILTER (WHERE e.event_type = 'exit') AS exits,
    COUNT(DISTINCT e.track_id) FILTER (WHERE e.event_type = 'entry') AS unique_visitors,
    COUNT(*) FILTER (WHERE e.event_type = 'reentry') AS reentries,
    COUNT(*) FILTER (WHERE e.event_type = 'group_entry') AS group_entries
FROM events e
GROUP BY DATE_TRUNC('hour', e.timestamp)
ORDER BY hour DESC;

CREATE OR REPLACE VIEW v_zone_occupancy_current AS
SELECT
    z.zone_id,
    z.name,
    z.zone_type,
    z.capacity,
    COALESCE(active.cnt, 0) AS current_count,
    ROUND(COALESCE(active.cnt, 0)::NUMERIC / NULLIF(z.capacity, 0) * 100, 1) AS utilization_pct
FROM zones z
LEFT JOIN (
    SELECT
        entry_zone AS zone_id,
        COUNT(*) AS cnt
    FROM sessions
    WHERE is_complete = FALSE
    GROUP BY entry_zone
) active ON z.zone_id = active.zone_id;

-- Done
SELECT 'Schema initialized successfully' AS status;
