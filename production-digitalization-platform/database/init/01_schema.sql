-- =====================================================================
-- Production digitalization platform - database schema
-- Runs automatically on the first start of the TimescaleDB container.
-- Layers:  raw (as received)  ->  clean (harmonized)  ->  kpi (aggregated)
-- =====================================================================

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB not available - running on plain PostgreSQL';
END $$;

CREATE SCHEMA IF NOT EXISTS master;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS clean;
CREATE SCHEMA IF NOT EXISTS kpi;

-- ---------------------------------------------------------------------
-- MASTER DATA
-- ---------------------------------------------------------------------
CREATE TABLE master.stations (
    station_id     TEXT PRIMARY KEY,          -- canonical id, e.g. ST30
    name           TEXT NOT NULL,
    sequence       INT  NOT NULL,
    ideal_cycle_s  DOUBLE PRECISION NOT NULL, -- engineering standard time per part
    uses_compressed_air BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO master.stations VALUES
    ('ST10', 'Kitting',                 1, 40, FALSE),
    ('ST20', 'Frame assembly',          2, 60, FALSE),
    ('ST30', 'Panel bonding',           3, 75, TRUE),
    ('ST40', 'Electrical installation', 4, 55, FALSE),
    ('ST50', 'Final inspection',        5, 45, FALSE);

CREATE TABLE master.assets (
    asset_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    asset_type  TEXT NOT NULL,
    supplies    TEXT REFERENCES master.stations(station_id)
);

INSERT INTO master.assets VALUES
    ('compressor01', 'Air production unit (compressor)', 'compressor', 'ST30');

-- ---------------------------------------------------------------------
-- RAW LAYER - every message exactly as received (audit trail, reprocessing)
-- ---------------------------------------------------------------------
CREATE TABLE raw.messages (
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    topic       TEXT NOT NULL,
    payload     JSONB NOT NULL
);
CREATE INDEX ON raw.messages (received_at DESC);

CREATE TABLE raw.rejected_messages (
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    topic       TEXT NOT NULL,
    payload     TEXT,
    error       TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- CLEAN LAYER - harmonized, typed, de-duplicated
-- ---------------------------------------------------------------------
CREATE TABLE clean.sensor_readings (
    ts               TIMESTAMPTZ NOT NULL,
    machine_id       TEXT NOT NULL,
    source_ts        TIMESTAMP,              -- original timestamp in the dataset
    tp2              REAL, tp3 REAL, h1 REAL, dv_pressure REAL, reservoirs REAL,
    oil_temperature  REAL, motor_current REAL,
    comp REAL, dv_electric REAL, towers REAL, mpg REAL, lps REAL,
    pressure_switch REAL, oil_level REAL, caudal_impulses REAL,
    dq_flag          TEXT                    -- NULL = ok, otherwise reason
);
CREATE INDEX ON clean.sensor_readings (machine_id, ts DESC);

CREATE TABLE clean.line_events (
    ts          TIMESTAMPTZ NOT NULL,
    station_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,   -- order_released | cycle_start | cycle_end | downtime_start | downtime_end | order_completed
    order_id    TEXT,
    duration_s  DOUBLE PRECISION,
    result      TEXT,            -- good | scrap (cycle_end, order_completed)
    reason      TEXT             -- downtime reason code
);
CREATE INDEX ON clean.line_events (station_id, ts DESC);
CREATE INDEX ON clean.line_events (event_type, ts DESC);

CREATE TABLE clean.rfid_reads (
    ts          TIMESTAMPTZ NOT NULL,
    epc         TEXT NOT NULL,   -- RFID tag id (one tag per part carrier)
    order_id    TEXT,
    station_id  TEXT NOT NULL,
    direction   TEXT NOT NULL,   -- in | out
    rssi        REAL
);
CREATE INDEX ON clean.rfid_reads (epc, ts);
CREATE INDEX ON clean.rfid_reads (station_id, ts DESC);

CREATE TABLE clean.machine_health (
    ts              TIMESTAMPTZ NOT NULL,
    machine_id      TEXT NOT NULL,
    source_ts       TIMESTAMP,
    health_score    REAL NOT NULL,
    health_forest   REAL,
    health_zscore   REAL,
    status          TEXT NOT NULL,   -- normal | warning | alarm
    contributors    JSONB
);
CREATE INDEX ON clean.machine_health (machine_id, ts DESC);

CREATE TABLE clean.alarms (
    alarm_id        SERIAL PRIMARY KEY,
    machine_id      TEXT NOT NULL,
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    source_ts_open  TIMESTAMP,
    source_ts_close TIMESTAMP,
    min_health      REAL,
    severity        TEXT NOT NULL DEFAULT 'high',
    contributors    JSONB,
    status          TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE clean.ai_recommendations (
    rec_id              SERIAL PRIMARY KEY,
    alarm_id            INT REFERENCES clean.alarms(alarm_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider            TEXT NOT NULL,
    likely_cause        TEXT,
    recommended_actions JSONB,
    urgency             TEXT,
    confidence          TEXT,
    evidence            TEXT,
    knowledge_sources   JSONB,
    raw_response        TEXT
);

-- ---------------------------------------------------------------------
-- KPI LAYER - written by the KPI engine, read by dashboards / Power BI
-- ---------------------------------------------------------------------
CREATE TABLE kpi.station_kpis (
    bucket          TIMESTAMPTZ NOT NULL,
    station_id      TEXT NOT NULL,
    planned_s       DOUBLE PRECISION,
    downtime_s      DOUBLE PRECISION,
    run_s           DOUBLE PRECISION,
    total_count     INT,
    good_count      INT,
    scrap_count     INT,
    availability    DOUBLE PRECISION,
    performance     DOUBLE PRECISION,
    quality         DOUBLE PRECISION,
    oee             DOUBLE PRECISION,
    failures        INT,
    mtbf_s          DOUBLE PRECISION,
    mttr_s          DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (bucket, station_id)
);

CREATE TABLE kpi.line_kpis (
    bucket              TIMESTAMPTZ PRIMARY KEY,
    completed_count     INT,
    good_count          INT,
    scrap_count         INT,
    first_pass_yield    DOUBLE PRECISION,
    throughput_per_hour DOUBLE PRECISION,
    line_oee            DOUBLE PRECISION,   -- OEE of the bottleneck station
    bottleneck_station  TEXT,
    avg_lead_time_s     DOUBLE PRECISION,
    wip_end             INT,
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE kpi.order_lead_times (
    order_id        TEXT PRIMARY KEY,
    epc             TEXT,
    released_at     TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    lead_time_s     DOUBLE PRECISION,
    value_add_s     DOUBLE PRECISION,   -- time inside stations
    waiting_s       DOUBLE PRECISION,   -- time in buffers between stations
    flow_efficiency DOUBLE PRECISION,
    result          TEXT
);

CREATE TABLE kpi.station_flow (
    bucket          TIMESTAMPTZ NOT NULL,
    station_id      TEXT NOT NULL,
    parts           INT,
    avg_dwell_s     DOUBLE PRECISION,   -- RFID in -> out at this station
    avg_wait_before_s DOUBLE PRECISION, -- RFID out previous station -> in this station
    PRIMARY KEY (bucket, station_id)
);

CREATE TABLE kpi.downtime_reasons (
    bucket          TIMESTAMPTZ NOT NULL,
    station_id      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    events          INT,
    downtime_s      DOUBLE PRECISION,
    PRIMARY KEY (bucket, station_id, reason)
);

CREATE TABLE kpi.data_quality (
    bucket          TIMESTAMPTZ PRIMARY KEY,
    raw_messages    INT,
    rejected        INT,
    rfid_duplicates INT,
    sensor_flagged  INT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE kpi.sensor_limits (
    machine_id  TEXT NOT NULL,
    sensor      TEXT NOT NULL,
    unit        TEXT,
    lower_limit DOUBLE PRECISION,
    center      DOUBLE PRECISION,
    upper_limit DOUBLE PRECISION,
    PRIMARY KEY (machine_id, sensor)
);

CREATE TABLE kpi.ai_summaries (
    summary_id  SERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    period_start TIMESTAMPTZ,
    period_end  TIMESTAMPTZ,
    provider    TEXT,
    summary     TEXT
);

-- ---------------------------------------------------------------------
-- TimescaleDB hypertables + retention (skipped on plain PostgreSQL)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('raw.messages', 'received_at', chunk_time_interval => INTERVAL '1 hour');
        PERFORM create_hypertable('clean.sensor_readings', 'ts', chunk_time_interval => INTERVAL '6 hours');
        PERFORM create_hypertable('clean.line_events', 'ts', chunk_time_interval => INTERVAL '1 day');
        PERFORM create_hypertable('clean.rfid_reads', 'ts', chunk_time_interval => INTERVAL '1 day');
        PERFORM create_hypertable('clean.machine_health', 'ts', chunk_time_interval => INTERVAL '1 day');
        PERFORM add_retention_policy('raw.messages', INTERVAL '3 days');
        PERFORM add_retention_policy('clean.sensor_readings', INTERVAL '14 days');
    END IF;
END $$;
