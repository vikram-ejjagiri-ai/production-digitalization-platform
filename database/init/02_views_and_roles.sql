-- =====================================================================
-- Reporting views (used by Power BI and the management dashboard)
-- and read-only roles for BI tools.
-- =====================================================================

CREATE OR REPLACE VIEW kpi.v_station_oee AS
SELECT k.bucket, k.station_id, s.name AS station_name, s.sequence,
       k.availability, k.performance, k.quality, k.oee,
       k.total_count, k.good_count, k.scrap_count,
       k.planned_s, k.run_s, k.downtime_s, k.mtbf_s, k.mttr_s
FROM kpi.station_kpis k
JOIN master.stations s USING (station_id);

CREATE OR REPLACE VIEW kpi.v_station_oee_daily AS
SELECT date_trunc('day', bucket) AS day, station_id,
       SUM(run_s) / NULLIF(SUM(planned_s), 0)                                   AS availability,
       LEAST(1, SUM(total_count * st.ideal_cycle_s) / NULLIF(SUM(run_s), 0))    AS performance,
       SUM(good_count)::float / NULLIF(SUM(total_count), 0)                     AS quality,
       (SUM(run_s) / NULLIF(SUM(planned_s), 0))
         * LEAST(1, SUM(total_count * st.ideal_cycle_s) / NULLIF(SUM(run_s), 0))
         * (SUM(good_count)::float / NULLIF(SUM(total_count), 0))               AS oee
FROM kpi.station_kpis k
JOIN master.stations st USING (station_id)
GROUP BY 1, 2;

CREATE OR REPLACE VIEW kpi.v_downtime_pareto AS
SELECT station_id, reason, SUM(events) AS events, SUM(downtime_s) / 60.0 AS downtime_min
FROM kpi.downtime_reasons
GROUP BY station_id, reason;

CREATE OR REPLACE VIEW kpi.v_alarm_log AS
SELECT a.alarm_id, a.machine_id, a.opened_at, a.closed_at, a.status, a.min_health,
       a.source_ts_open AS dataset_time,
       r.likely_cause, r.urgency, r.recommended_actions, r.provider
FROM clean.alarms a
LEFT JOIN LATERAL (
    SELECT * FROM clean.ai_recommendations x
    WHERE x.alarm_id = a.alarm_id ORDER BY x.created_at DESC LIMIT 1
) r ON TRUE;

-- Read-only login for Power BI / Excel / any BI tool
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_reader') THEN
        CREATE ROLE bi_reader LOGIN PASSWORD 'bi_reader';
    END IF;
END $$;
GRANT USAGE ON SCHEMA master, clean, kpi TO bi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA master, clean, kpi TO bi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA master, clean, kpi GRANT SELECT ON TABLES TO bi_reader;
