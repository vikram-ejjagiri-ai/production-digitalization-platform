"""KPI engine: recalculates shopfloor KPIs from the clean layer on a schedule.

Every KPI_INTERVAL_S seconds it reloads the last KPI_LOOKBACK_HOURS of clean
data, recomputes all KPI buckets in that range and upserts them. Recomputing
(instead of incrementally adding) keeps results correct when late messages
arrive - a common issue with shopfloor data.
"""
import time

import pandas as pd

from common import config, db
from common.log import get_logger
from services.kpi_engine import kpis

log = get_logger("kpi-engine")


def query_df(conn, sql: str, params=None) -> pd.DataFrame:
    with db.cursor(conn) as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    for c in ("ts", "start", "end"):
        if c in df and len(df):
            df[c] = pd.to_datetime(df[c], utc=True)
    return df


def nan_to_none(rows: list[tuple]) -> list[tuple]:
    return [tuple(None if (isinstance(v, float) and pd.isna(v)) else v for v in r) for r in rows]


def upsert(cur, table: str, df: pd.DataFrame, keys: list[str]) -> None:
    if df.empty:
        return
    cols = list(df.columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in keys)
    rows = nan_to_none([tuple(r) for r in df.itertuples(index=False, name=None)])
    rows = [tuple(v.to_pydatetime() if isinstance(v, pd.Timestamp) else v for v in r) for r in rows]
    db.insert_many(cur, table, cols, rows, on_conflict=f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}")


def data_quality(conn, buckets, minutes) -> pd.DataFrame:
    if not buckets:
        return pd.DataFrame()
    start = buckets[0].to_pydatetime()
    width = f"{minutes} minutes"
    sql = f"""
    WITH b AS (SELECT generate_series(%(s)s::timestamptz, now(), %(w)s::interval) AS bucket)
    SELECT b.bucket,
      (SELECT count(*) FROM raw.messages m WHERE m.received_at >= b.bucket AND m.received_at < b.bucket + %(w)s::interval) AS raw_messages,
      (SELECT count(*) FROM raw.rejected_messages r WHERE r.received_at >= b.bucket AND r.received_at < b.bucket + %(w)s::interval) AS rejected,
      GREATEST(0,
        (SELECT count(*) FROM raw.messages m WHERE m.topic LIKE '%%/rfid' AND m.received_at >= b.bucket AND m.received_at < b.bucket + %(w)s::interval)
      - (SELECT count(*) FROM clean.rfid_reads c WHERE c.ts >= b.bucket AND c.ts < b.bucket + %(w)s::interval)) AS rfid_duplicates,
      (SELECT count(*) FROM clean.sensor_readings s WHERE s.dq_flag IS NOT NULL AND s.ts >= b.bucket AND s.ts < b.bucket + %(w)s::interval) AS sensor_flagged
    FROM b"""
    return query_df(conn, sql, {"s": start, "w": width})


def run_once(conn) -> dict:
    now = kpis.to_utc_now()
    since = kpis.lookback_start(now, config.KPI_LOOKBACK_HOURS)
    load_from = since - pd.Timedelta(hours=1)  # margin so orders/stops that started earlier are paired
    stations = query_df(conn, "SELECT station_id, sequence, ideal_cycle_s FROM master.stations ORDER BY sequence")
    events = query_df(conn, "SELECT ts, station_id, event_type, order_id, duration_s, result, reason "
                            "FROM clean.line_events WHERE ts >= %s ORDER BY ts", (load_from.to_pydatetime(),))
    rfid = query_df(conn, "SELECT ts, epc, order_id, station_id, direction FROM clean.rfid_reads "
                          "WHERE ts >= %s ORDER BY ts", (load_from.to_pydatetime(),))
    first = query_df(conn, "SELECT min(ts) AS ts FROM clean.line_events")
    if events.empty or first.ts.isna().all():
        return {"status": "no line data yet"}
    observed_since = first.ts.iloc[0]

    buckets = kpis.bucket_starts(max(since, observed_since), now, config.KPI_BUCKET_MINUTES)
    st, reasons = kpis.station_kpis(events, stations, buckets, config.KPI_BUCKET_MINUTES, now, observed_since,
                                    ideal_scale=config.LINE_TIME_SCALE)
    leads = kpis.order_lead_times(rfid, events)
    flow = kpis.station_flow(rfid, stations, buckets, config.KPI_BUCKET_MINUTES)
    line = kpis.line_kpis(events, st, leads, stations, buckets, config.KPI_BUCKET_MINUTES)
    dq = data_quality(conn, buckets, config.KPI_BUCKET_MINUTES)

    with db.cursor(conn) as cur:
        upsert(cur, "kpi.station_kpis", st, ["bucket", "station_id"])
        if buckets:
            cur.execute("DELETE FROM kpi.downtime_reasons WHERE bucket >= %s", (buckets[0].to_pydatetime(),))
        upsert(cur, "kpi.downtime_reasons", reasons, ["bucket", "station_id", "reason"])
        upsert(cur, "kpi.order_lead_times", leads, ["order_id"])
        upsert(cur, "kpi.station_flow", flow, ["bucket", "station_id"])
        upsert(cur, "kpi.line_kpis", line, ["bucket"])
        upsert(cur, "kpi.data_quality", dq, ["bucket"])
    latest = line.iloc[-1].to_dict() if not line.empty else {}
    return {"buckets": len(buckets), "orders": len(leads), "line_oee": latest.get("line_oee"),
            "wip": latest.get("wip_end")}


def main() -> None:
    conn = db.connect()
    log.info("KPI engine running every %ss (buckets of %s min).", config.KPI_INTERVAL_S, config.KPI_BUCKET_MINUTES)
    while True:
        try:
            log.info("KPIs updated: %s", run_once(conn))
        except Exception as exc:
            log.exception("KPI run failed: %s", exc)
            try:
                conn.close()
            except Exception:
                pass
            conn = db.connect()
        time.sleep(config.KPI_INTERVAL_S)


if __name__ == "__main__":
    main()
