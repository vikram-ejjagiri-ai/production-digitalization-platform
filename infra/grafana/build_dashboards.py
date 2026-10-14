"""Dashboards as code: generates the Grafana dashboard JSON files.

    python infra/grafana/build_dashboards.py

Edit the panel definitions here instead of clicking in the UI, so dashboards are
versioned, reviewable and reproducible. Grafana loads the generated files from
infra/grafana/dashboards/ at startup (provisioning).
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "tsdb"}
GREEN, YELLOW, RED, BLUE = "green", "#EAB839", "red", "#5794F2"

_id = 0


def _next_id():
    global _id
    _id += 1
    return _id


def target(sql: str, fmt: str = "table", ref: str = "A") -> dict:
    return {"refId": ref, "datasource": DS, "rawQuery": True, "editorMode": "code", "format": fmt, "rawSql": sql.strip()}


def thresholds(*steps):
    """steps: (color, value) pairs; the first value is ignored (base)."""
    return {"mode": "absolute", "steps": [{"color": c, "value": None if i == 0 else v} for i, (c, v) in enumerate(steps)]}


def base(title, kind, grid, targets, description="", unit=None, decimals=None, th=None, overrides=None, options=None,
         custom=None, mappings=None, minv=None, maxv=None, color=None):
    defaults = {}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if th:
        defaults["thresholds"] = th
    if custom:
        defaults["custom"] = custom
    if mappings:
        defaults["mappings"] = mappings
    if minv is not None:
        defaults["min"] = minv
    if maxv is not None:
        defaults["max"] = maxv
    if color:
        defaults["color"] = color
    return {
        "id": _next_id(), "type": kind, "title": title, "description": description, "datasource": DS,
        "gridPos": dict(zip(("x", "y", "w", "h"), grid)), "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options or {},
    }


def stat(title, sql, grid, unit=None, th=None, decimals=None, description="", text_mode="value", color_mode="background",
         text_value=False):
    return base(title, "stat", grid, [target(sql)], description, unit, decimals,
                th or thresholds((BLUE, None)), color={"mode": "thresholds"},
                options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/" if text_value else "",
                                           "values": False},
                         "colorMode": color_mode, "graphMode": "none", "textMode": text_mode, "justifyMode": "center"})


def gauge(title, sql, grid, unit=None, th=None, minv=0, maxv=100, description=""):
    return base(title, "gauge", grid, [target(sql)], description, unit, 0, th, minv=minv, maxv=maxv,
                options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                         "showThresholdMarkers": True, "showThresholdLabels": False})


def timeseries(title, sqls, grid, unit=None, description="", th=None, th_style="off", overrides=None, minv=None,
               maxv=None, fill=10, fmt="time_series", stacking="none", draw="line"):
    targets = [target(s, fmt, chr(65 + i)) for i, s in enumerate(sqls)]
    custom = {"drawStyle": draw, "lineWidth": 2, "fillOpacity": fill, "showPoints": "never", "spanNulls": True,
              "thresholdsStyle": {"mode": th_style}, "stacking": {"mode": stacking, "group": "A"}}
    return base(title, "timeseries", grid, targets, description, unit, None, th, overrides, custom=custom,
                minv=minv, maxv=maxv, color={"mode": "palette-classic"},
                options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                         "tooltip": {"mode": "multi", "sort": "none"}})


def table(title, sql, grid, overrides=None, description="", unit=None):
    return base(title, "table", grid, [target(sql)], description, unit, overrides=overrides,
                custom={"align": "auto", "cellOptions": {"type": "auto"}, "inspect": True},
                options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False}})


def barchart(title, sql, grid, unit=None, horizontal=False, description="", stacking="none", overrides=None, maxv=None):
    return base(title, "barchart", grid, [target(sql)], description, unit, 1, overrides=overrides, maxv=maxv,
                color={"mode": "palette-classic"}, custom={"fillOpacity": 85, "lineWidth": 0},
                options={"orientation": "horizontal" if horizontal else "auto", "showValue": "auto",
                         "stacking": stacking, "groupWidth": 0.7, "barWidth": 0.9, "xTickLabelRotation": 0,
                         "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                         "tooltip": {"mode": "multi", "sort": "none"}})


def bargauge(title, sql, grid, unit=None, th=None, description="", minv=0, maxv=1):
    return base(title, "bargauge", grid, [target(sql)], description, unit, 0, th, minv=minv, maxv=maxv,
                color={"mode": "thresholds"},
                options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                         "orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                         "valueMode": "color", "namePlacement": "auto", "sizing": "auto"})


def text(title, md, grid):
    p = base(title, "text", grid, [], options={"mode": "markdown", "content": md})
    p.pop("datasource")
    p.pop("targets")
    return p


def override(name, props):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": k, "value": v} for k, v in props.items()]}


def cell_color(name, mapping=None, th=None, unit=None):
    props = {"custom.cellOptions": {"type": "color-background", "mode": "basic"}}
    if mapping:
        props["mappings"] = mapping
    if th:
        props["thresholds"] = th
    if unit:
        props["unit"] = unit
    return override(name, props)


def value_map(pairs):
    return [{"type": "value", "options": {k: {"color": c, "index": i} for i, (k, c) in enumerate(pairs)}}]


OEE_TH = thresholds((RED, None), (YELLOW, 0.6), (GREEN, 0.75))
HEALTH_TH = thresholds((RED, None), (YELLOW, 50), (GREEN, 70))


def dashboard(uid, title, panels, time_from, refresh, description, tags):
    return {
        "uid": uid, "title": title, "description": description, "tags": tags, "timezone": "browser",
        "editable": True, "graphTooltip": 1, "refresh": refresh, "schemaVersion": 39, "version": 1,
        "time": {"from": time_from, "to": "now"}, "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
        "templating": {"list": []}, "annotations": {"list": [{
            "name": "Compressor alarms", "enable": True, "iconColor": "red", "datasource": DS,
            "target": target("SELECT opened_at AS time, coalesce(closed_at, now()) AS timeend, "
                             "'Compressor alarm #' || alarm_id AS text FROM clean.alarms "
                             "WHERE opened_at < $__timeTo() AND coalesce(closed_at, now()) > $__timeFrom()")}]},
        "links": [{"title": d, "type": "link", "url": f"/d/{u}", "icon": "dashboard", "targetBlank": False}
                  for u, d in (("shopfloor", "Shopfloor"), ("management", "Management"), ("asset-health", "Compressor health"))],
        "panels": panels,
    }


ALARM_SQL = """
SELECT alarm_id AS "Alarm", opened_at AS "Opened", status AS "Status", dataset_time AS "Dataset time",
       round(min_health::numeric, 0) AS "Min health", urgency AS "Urgency", likely_cause AS "Likely cause",
       (SELECT string_agg(value, '  |  ') FROM jsonb_array_elements_text(recommended_actions)) AS "Recommended actions",
       provider AS "Advisor"
FROM kpi.v_alarm_log {where} ORDER BY opened_at DESC LIMIT {limit}"""

ALARM_OVERRIDES = [
    cell_color("Status", value_map([("open", RED), ("closed", GREEN)])),
    cell_color("Urgency", value_map([("high", RED), ("medium", YELLOW), ("low", GREEN)])),
    override("Recommended actions", {"custom.width": 520, "custom.cellOptions": {"type": "auto", "wrapText": True}}),
    override("Likely cause", {"custom.width": 300, "custom.cellOptions": {"type": "auto", "wrapText": True}}),
    override("Alarm", {"custom.width": 70}),
]


def shopfloor():
    p = [
        stat("Line OEE (now)", "SELECT line_oee FROM kpi.line_kpis WHERE line_oee IS NOT NULL ORDER BY bucket DESC LIMIT 1",
             (0, 0, 4, 4), "percentunit", OEE_TH, 0, "OEE of the bottleneck station (ST30) in the current KPI bucket"),
        stat("Good parts (1 h)", "SELECT count(*) FROM clean.line_events WHERE event_type = 'order_completed' "
             "AND result = 'good' AND ts > now() - interval '1 hour'", (4, 0, 3, 4), "none", color_mode="value"),
        stat("First pass yield (1 h)", "SELECT avg(CASE WHEN result = 'good' THEN 1.0 ELSE 0.0 END) FROM clean.line_events "
             "WHERE event_type = 'order_completed' AND ts > now() - interval '1 hour'", (7, 0, 3, 4), "percentunit",
             thresholds((RED, None), (YELLOW, 0.95), (GREEN, 0.97)), 1),
        stat("WIP (parts in line)", "SELECT (SELECT count(*) FROM clean.line_events WHERE event_type = 'order_released') - "
             "(SELECT count(*) FROM clean.line_events WHERE event_type = 'order_completed')", (10, 0, 3, 4), "none",
             thresholds((GREEN, None), (YELLOW, 10), (RED, 12))),
        gauge("Compressor health", "SELECT health_score FROM clean.machine_health ORDER BY ts DESC LIMIT 1",
              (13, 0, 4, 4), "none", HEALTH_TH, description="100 = like commissioning data, below 50 = alarm"),
        stat("Open machine alarms", "SELECT count(*) FROM clean.alarms WHERE status = 'open'", (17, 0, 3, 4), "none",
             thresholds((GREEN, None), (RED, 1))),
        stat("Dataset time (replay)", "SELECT to_char(max(source_ts), 'YYYY-MM-DD HH24:MI') FROM clean.sensor_readings "
             "WHERE ts > now() - interval '5 minutes'", (20, 0, 4, 4), text_mode="value", color_mode="none", text_value=True,
             description="Original timestamp of the machine data currently being replayed"),
        table("Station status", """
WITH last AS (
  SELECT DISTINCT ON (station_id) station_id, event_type, reason, ts
  FROM clean.line_events WHERE event_type IN ('downtime_start','downtime_end','cycle_start','cycle_end')
  ORDER BY station_id, ts DESC)
SELECT s.station_id AS "Station", s.name AS "Name",
       CASE WHEN l.event_type = 'downtime_start' THEN 'DOWN'
            WHEN l.event_type = 'cycle_start' THEN 'RUNNING'
            WHEN l.event_type IS NULL THEN 'NO DATA' ELSE 'WAITING' END AS "State",
       CASE WHEN l.event_type = 'downtime_start' THEN l.reason END AS "Stop reason",
       round(extract(epoch FROM now() - l.ts)) AS "In state [s]",
       k.oee AS "OEE (bucket)", k.good_count AS "Good (bucket)"
FROM master.stations s
LEFT JOIN last l USING (station_id)
LEFT JOIN LATERAL (SELECT oee, good_count FROM kpi.station_kpis k WHERE k.station_id = s.station_id
                   ORDER BY bucket DESC LIMIT 1) k ON TRUE
ORDER BY s.sequence""", (0, 4, 12, 8), [
            cell_color("State", value_map([("DOWN", RED), ("RUNNING", GREEN), ("WAITING", YELLOW), ("NO DATA", "gray")])),
            cell_color("OEE (bucket)", th=OEE_TH, unit="percentunit"),
        ], "WAITING = starved (no part) or blocked (next buffer full)"),
        timeseries("Compressor health score", ["SELECT ts AS time, health_score AS \"Health\" FROM clean.machine_health "
                                               "WHERE $__timeFilter(ts) ORDER BY 1"],
                   (12, 4, 12, 8), "none", th=HEALTH_TH, th_style="line+area", minv=0, maxv=100,
                   description="Ensemble of Isolation Forest + SPC z-score, trained on commissioning data (Part 1)"),
        timeseries("Compressor pressures", ["""
SELECT $__timeGroupAlias(ts, '10s'), avg(reservoirs) AS "Reservoirs", avg(tp2) AS "TP2 compressor", avg(tp3) AS "TP3 panel"
FROM clean.sensor_readings WHERE $__timeFilter(ts) GROUP BY 1 ORDER BY 1"""], (0, 12, 12, 8), "pressurebar", fill=0),
        bargauge("Station OEE (last 15 min)", """
SELECT k.station_id AS "Station",
       (sum(k.run_s) / nullif(sum(k.planned_s), 0))
       * least(1, sum(k.total_count * s.ideal_cycle_s) / nullif(sum(k.run_s), 0))
       * (sum(k.good_count)::float / nullif(sum(k.total_count), 0)) AS "OEE"
FROM kpi.station_kpis k JOIN master.stations s USING (station_id)
WHERE k.bucket > now() - interval '15 minutes'
GROUP BY k.station_id, s.sequence ORDER BY s.sequence""", (12, 12, 12, 8), "percentunit", OEE_TH),
        table("Active / recent compressor alarms with AI recommendation",
              ALARM_SQL.format(where="WHERE status = 'open' OR closed_at > now() - interval '30 minutes'", limit=5),
              (0, 20, 24, 8), ALARM_OVERRIDES),
    ]
    return dashboard("shopfloor", "Line 1 - Shopfloor (live)", p, "now-30m", "5s",
                     "Real-time view for operators and team leads", ["shopfloor", "line1"])


def management():
    period_oee = """
SELECT (sum(k.run_s) / nullif(sum(k.planned_s), 0))
       * least(1, sum(k.total_count * s.ideal_cycle_s) / nullif(sum(k.run_s), 0))
       * (sum(k.good_count)::float / nullif(sum(k.total_count), 0))
FROM kpi.station_kpis k JOIN master.stations s USING (station_id)
WHERE $__timeFilter(k.bucket) AND k.station_id = 'ST30'"""
    p = [
        stat("Line OEE (period)", period_oee, (0, 0, 4, 4), "percentunit", OEE_TH, 1,
             "OEE of the bottleneck station ST30 over the selected period"),
        stat("Good parts", "SELECT sum(good_count) FROM kpi.line_kpis WHERE $__timeFilter(bucket)", (4, 0, 4, 4), "none",
             color_mode="value"),
        stat("First pass yield", "SELECT sum(good_count)::float / nullif(sum(completed_count), 0) FROM kpi.line_kpis "
             "WHERE $__timeFilter(bucket)", (8, 0, 4, 4), "percentunit", thresholds((RED, None), (YELLOW, 0.95), (GREEN, 0.97)), 1),
        stat("Avg lead time", "SELECT avg(lead_time_s) FROM kpi.order_lead_times WHERE $__timeFilter(completed_at)",
             (12, 0, 4, 4), "s", decimals=0, color_mode="value", description="Release to completion, measured with RFID"),
        stat("Throughput", "SELECT avg(throughput_per_hour) FROM kpi.line_kpis WHERE $__timeFilter(bucket)",
             (16, 0, 4, 4), "none", decimals=1,
             color_mode="value", description="Good parts per hour"),
        stat("Machine alarms", "SELECT count(*) FROM clean.alarms WHERE $__timeFilter(opened_at)", (20, 0, 4, 4), "none",
             thresholds((GREEN, None), (YELLOW, 1), (RED, 3))),
        timeseries("OEE trend by station", ["SELECT bucket AS time, station_id AS metric, oee AS value FROM kpi.station_kpis "
                                            "WHERE $__timeFilter(bucket) ORDER BY 1"],
                   (0, 4, 12, 9), "percentunit", fill=0, minv=0, maxv=1, th=OEE_TH, th_style="dashed"),
        barchart("OEE breakdown by station (A x P x Q)", """
SELECT k.station_id AS "Station",
       sum(k.run_s) / nullif(sum(k.planned_s), 0) AS "Availability",
       least(1, sum(k.total_count * s.ideal_cycle_s) / nullif(sum(k.run_s), 0)) AS "Performance",
       sum(k.good_count)::float / nullif(sum(k.total_count), 0) AS "Quality"
FROM kpi.station_kpis k JOIN master.stations s USING (station_id)
WHERE $__timeFilter(k.bucket) GROUP BY k.station_id, s.sequence ORDER BY s.sequence""", (12, 4, 12, 9), "percentunit", maxv=1),
        barchart("Downtime Pareto (minutes)", """
SELECT reason AS "Reason", sum(downtime_s) / 60 AS "Downtime"
FROM kpi.downtime_reasons WHERE $__timeFilter(bucket) GROUP BY reason ORDER BY 2 DESC""", (0, 13, 12, 8), "m",
                 horizontal=True),
        barchart("Downtime by station and reason (minutes)", """
SELECT station_id AS "Station",
       sum(downtime_s) FILTER (WHERE reason = 'material_missing') / 60 AS "material missing",
       sum(downtime_s) FILTER (WHERE reason = 'machine_fault') / 60 AS "machine fault",
       sum(downtime_s) FILTER (WHERE reason = 'tool_change') / 60 AS "tool change",
       sum(downtime_s) FILTER (WHERE reason = 'quality_check') / 60 AS "quality check",
       sum(downtime_s) FILTER (WHERE reason = 'operator_absent') / 60 AS "operator absent",
       sum(downtime_s) FILTER (WHERE reason = 'low_air_pressure') / 60 AS "low air pressure"
FROM kpi.downtime_reasons WHERE $__timeFilter(bucket) GROUP BY station_id ORDER BY station_id""",
                 (12, 13, 12, 8), "m", stacking="normal"),
        timeseries("Lead time from RFID (per order)", ["""
SELECT completed_at AS time, lead_time_s / 60 AS "Lead time", waiting_s / 60 AS "Waiting in buffers"
FROM kpi.order_lead_times WHERE $__timeFilter(completed_at) ORDER BY 1"""], (0, 21, 12, 8), "m", fill=0, draw="points"),
        table("Material flow by station (RFID)", """
SELECT f.station_id AS "Station", s.name AS "Name", sum(f.parts) AS "Parts",
       round((sum(f.avg_dwell_s * f.parts) / nullif(sum(f.parts), 0))::numeric, 1) AS "Avg time in station [s]",
       round((sum(f.avg_wait_before_s * f.parts) / nullif(sum(f.parts) FILTER (WHERE f.avg_wait_before_s IS NOT NULL), 0))::numeric, 1)
         AS "Avg wait before station [s]",
       s.ideal_cycle_s AS "Ideal cycle [s]"
FROM kpi.station_flow f JOIN master.stations s USING (station_id)
WHERE $__timeFilter(f.bucket) GROUP BY f.station_id, s.name, s.sequence, s.ideal_cycle_s ORDER BY s.sequence""",
              (12, 21, 12, 8), [cell_color("Avg wait before station [s]",
                                           th=thresholds((GREEN, None), (YELLOW, 60), (RED, 180)))],
              "Long waits in front of a station point to the bottleneck"),
        table("Reliability by station", """
SELECT station_id AS "Station", sum(failures) AS "Stops",
       round((sum(downtime_s) / 60)::numeric, 1) AS "Downtime [min]",
       round((sum(run_s) / nullif(sum(failures), 0) / 60)::numeric, 1) AS "MTBF [min]",
       round((sum(downtime_s) / nullif(sum(failures), 0) / 60)::numeric, 1) AS "MTTR [min]",
       sum(scrap_count) AS "Scrap"
FROM kpi.station_kpis WHERE $__timeFilter(bucket) GROUP BY station_id ORDER BY station_id""", (0, 29, 12, 8)),
        timeseries("Data quality", ["SELECT bucket AS time, rejected AS \"Rejected messages\", rfid_duplicates AS "
                                    "\"Duplicate RFID reads removed\", sensor_flagged AS \"Flagged sensor rows\" "
                                    "FROM kpi.data_quality WHERE $__timeFilter(bucket) ORDER BY 1"],
                   (12, 29, 12, 8), "none", fill=20, draw="bars",
                   description="Counted by the harmonization layer; raw data is never modified"),
        table("AI shift summaries", "SELECT created_at AS \"Created\", provider AS \"Generated by\", summary AS \"Summary\" "
              "FROM kpi.ai_summaries WHERE $__timeFilter(created_at) ORDER BY created_at DESC LIMIT 10", (0, 37, 24, 8),
              [override("Summary", {"custom.cellOptions": {"type": "auto", "wrapText": True}}),
               override("Created", {"custom.width": 180}), override("Generated by", {"custom.width": 170})]),
        table("Alarm log with AI recommendations", ALARM_SQL.format(where="WHERE $__timeFilter(opened_at)", limit=50),
              (0, 45, 24, 9), ALARM_OVERRIDES),
    ]
    return dashboard("management", "Line 1 - Production KPIs (management)", p, "now-6h", "1m",
                     "OEE, losses, lead time, reliability and data quality for management reviews", ["management", "kpi"])


def sensor_with_limits(sensor, label, unit, grid):
    sql = f"""
SELECT $__timeGroupAlias(ts, '10s'), avg({sensor}) AS "{label}",
       (SELECT upper_limit FROM kpi.sensor_limits WHERE sensor = '{sensor}') AS "Commissioning P99",
       (SELECT lower_limit FROM kpi.sensor_limits WHERE sensor = '{sensor}') AS "Commissioning P1"
FROM clean.sensor_readings WHERE $__timeFilter(ts) GROUP BY 1 ORDER BY 1"""
    dashed = {"custom.lineStyle": {"fill": "dash", "dash": [10, 10]}, "custom.lineWidth": 1, "color": {"mode": "fixed", "fixedColor": "orange"}}
    return timeseries(f"{label} vs commissioning range", [sql], grid, unit, fill=0,
                      overrides=[override("Commissioning P99", dashed), override("Commissioning P1", dashed)])


def asset_health():
    p = [
        timeseries("Health score", ["SELECT ts AS time, health_score AS \"Health\" FROM clean.machine_health "
                                    "WHERE $__timeFilter(ts) ORDER BY 1"], (0, 0, 16, 8), "none", th=HEALTH_TH,
                   th_style="line+area", minv=0, maxv=100),
        gauge("Current health", "SELECT health_score FROM clean.machine_health ORDER BY ts DESC LIMIT 1", (16, 0, 4, 8),
              "none", HEALTH_TH),
        stat("Status", "SELECT upper(status) FROM clean.machine_health ORDER BY ts DESC LIMIT 1", (20, 0, 4, 4),
             th=thresholds((BLUE, None)), text_value=True),
        stat("Alarms (period)", "SELECT count(*) FROM clean.alarms WHERE $__timeFilter(opened_at)", (20, 4, 4, 4), "none",
             thresholds((GREEN, None), (RED, 1))),
        sensor_with_limits("reservoirs", "Reservoir pressure", "pressurebar", (0, 8, 12, 8)),
        sensor_with_limits("oil_temperature", "Oil temperature", "celsius", (12, 8, 12, 8)),
        sensor_with_limits("motor_current", "Motor current", "amp", (0, 16, 12, 8)),
        sensor_with_limits("tp2", "TP2 compressor pressure", "pressurebar", (12, 16, 12, 8)),
        table("Why? Top deviations in the latest window", """
SELECT c->>'feature' AS "Feature", c->>'sensor' AS "Sensor", (c->>'z')::float AS "z-score",
       c->>'direction' AS "Direction", (c->>'value')::float AS "Now", (c->>'baseline')::float AS "Commissioning baseline"
FROM (SELECT contributors FROM clean.machine_health ORDER BY ts DESC LIMIT 1) h,
     jsonb_array_elements(h.contributors) c""", (0, 24, 12, 8),
              [cell_color("z-score", th=thresholds((GREEN, None), (YELLOW, 3), (RED, 6)))],
              "Window features furthest from the healthy baseline learned in Part 1"),
        timeseries("Detector components", ["SELECT ts AS time, health_forest AS \"Isolation Forest\", health_zscore AS "
                                           "\"SPC z-score\" FROM clean.machine_health WHERE $__timeFilter(ts) ORDER BY 1"],
                   (12, 24, 12, 8), "none", fill=0, minv=0, maxv=100),
        table("Alarm history", ALARM_SQL.format(where="WHERE $__timeFilter(opened_at)", limit=50), (0, 32, 24, 8),
              ALARM_OVERRIDES),
    ]
    return dashboard("asset-health", "Compressor - Asset health (predictive maintenance)", p, "now-1h", "10s",
                     "Live machine health against the commissioning baseline", ["maintenance", "compressor"])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("shopfloor", shopfloor), ("management", management), ("asset_health", asset_health)):
        (OUT / f"{name}.json").write_text(json.dumps(fn(), indent=2))
        print("wrote", OUT / f"{name}.json")
