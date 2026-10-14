"""KPI calculations (pure pandas functions, unit tested in tests/test_kpis.py).

Definitions follow common shopfloor practice - see docs/kpi_definitions.md:
  Availability = run time / planned time
  Performance  = (ideal cycle time x total count) / run time      (capped at 100 %)
  Quality      = good count / total count
  OEE          = Availability x Performance x Quality
  MTBF         = run time / number of stops,  MTTR = downtime / number of stops
  Lead time    = last RFID read - first RFID read of a part carrier
  Flow efficiency = time inside stations / lead time
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def bucket_starts(start: datetime, end: datetime, minutes: int) -> list[pd.Timestamp]:
    first = pd.Timestamp(start).floor(f"{minutes}min")
    return list(pd.date_range(first, pd.Timestamp(end), freq=f"{minutes}min"))


def downtime_intervals(events: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Pair downtime_start / downtime_end per station. Open stops last until `now`."""
    dt = events[events.event_type.isin(["downtime_start", "downtime_end"])].sort_values("ts")
    rows = []
    for station, grp in dt.groupby("station_id"):
        open_start, open_reason = None, None
        for ev in grp.itertuples():
            if ev.event_type == "downtime_start":
                open_start, open_reason = ev.ts, ev.reason
            elif open_start is not None:
                rows.append((station, open_start, ev.ts, open_reason))
                open_start = None
        if open_start is not None:
            rows.append((station, open_start, now, open_reason))
    return pd.DataFrame(rows, columns=["station_id", "start", "end", "reason"])


def _overlap_s(intervals: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp) -> float:
    if intervals.empty or b <= a:
        return 0.0
    s = intervals["start"].clip(lower=a)
    e = intervals["end"].clip(upper=b)
    return float((e - s).dt.total_seconds().clip(lower=0).sum())


def _ratio(num, den):
    return float(num / den) if den and den > 0 else None


def station_kpis(events: pd.DataFrame, stations: pd.DataFrame, buckets: list[pd.Timestamp], bucket_minutes: int,
                 now: pd.Timestamp, observed_since: pd.Timestamp, ideal_scale: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (station_kpis, downtime_reasons) for every bucket x station."""
    intervals = downtime_intervals(events, now)
    ends = events[events.event_type == "cycle_end"]
    starts = events[events.event_type == "downtime_start"]
    out, reasons = [], []
    width = pd.Timedelta(minutes=bucket_minutes)
    for b in buckets:
        a = max(b, observed_since)
        z = min(b + width, now)
        if z <= a:
            continue
        planned = (z - a).total_seconds()
        for st in stations.itertuples():
            iv = intervals[intervals.station_id == st.station_id]
            down = min(_overlap_s(iv, a, z), planned)
            run = planned - down
            cyc = ends[(ends.station_id == st.station_id) & (ends.ts >= b) & (ends.ts < b + width)]
            total = int(len(cyc))
            good = int((cyc.result == "good").sum())
            stops = starts[(starts.station_id == st.station_id) & (starts.ts >= b) & (starts.ts < b + width)]
            n_stops = int(len(stops))
            availability = _ratio(run, planned)
            performance = min(1.0, total * st.ideal_cycle_s / ideal_scale / run) if run > 0 else None
            quality = _ratio(good, total)
            oee = availability * performance * quality if None not in (availability, performance, quality) else (
                0.0 if total == 0 and run > 0 else None)
            out.append({
                "bucket": b, "station_id": st.station_id, "planned_s": planned, "downtime_s": down, "run_s": run,
                "total_count": total, "good_count": good, "scrap_count": total - good,
                "availability": availability, "performance": performance, "quality": quality, "oee": oee,
                "failures": n_stops, "mtbf_s": run / n_stops if n_stops else None,
                "mttr_s": down / n_stops if n_stops else None,
            })
            for reason, grp in iv.groupby("reason"):
                d = _overlap_s(grp, a, z)
                n = int(((grp.start >= b) & (grp.start < b + width)).sum())
                if d > 0 or n > 0:
                    reasons.append({"bucket": b, "station_id": st.station_id, "reason": reason or "unknown",
                                    "events": n, "downtime_s": d})
    return pd.DataFrame(out), pd.DataFrame(reasons, columns=["bucket", "station_id", "reason", "events", "downtime_s"])


def order_lead_times(rfid: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Lead time, value-adding time and waiting time per completed order, from RFID reads."""
    done = events[events.event_type == "order_completed"][["order_id", "ts", "result"]].drop_duplicates("order_id")
    if done.empty or rfid.empty:
        return pd.DataFrame(columns=["order_id", "epc", "released_at", "completed_at", "lead_time_s",
                                     "value_add_s", "waiting_s", "flow_efficiency", "result"])
    reads = rfid[rfid.order_id.isin(done.order_id)]
    rows = []
    for order_id, grp in reads.groupby("order_id"):
        first, last = grp.ts.min(), grp.ts.max()
        lead = (last - first).total_seconds()
        value_add = 0.0
        for _, sg in grp.groupby("station_id"):
            ins, outs = sg[sg.direction == "in"].ts, sg[sg.direction == "out"].ts
            if len(ins) and len(outs):
                value_add += max(0.0, (outs.max() - ins.min()).total_seconds())
        rows.append({
            "order_id": order_id, "epc": grp.epc.iloc[0], "released_at": first, "completed_at": last,
            "lead_time_s": lead, "value_add_s": value_add, "waiting_s": max(0.0, lead - value_add),
            "flow_efficiency": value_add / lead if lead > 0 else None,
            "result": done.loc[done.order_id == order_id, "result"].iloc[0],
        })
    return pd.DataFrame(rows)


def station_flow(rfid: pd.DataFrame, stations: pd.DataFrame, buckets: list[pd.Timestamp], bucket_minutes: int) -> pd.DataFrame:
    """Average dwell time in each station and waiting time in the buffer before it."""
    if rfid.empty:
        return pd.DataFrame(columns=["bucket", "station_id", "parts", "avg_dwell_s", "avg_wait_before_s"])
    seq = dict(zip(stations.station_id, stations.sequence))
    firsts = rfid.groupby(["order_id", "station_id", "direction"]).ts.min().unstack("direction").reset_index()
    if "in" not in firsts or "out" not in firsts:
        return pd.DataFrame(columns=["bucket", "station_id", "parts", "avg_dwell_s", "avg_wait_before_s"])
    firsts["dwell_s"] = (firsts["out"] - firsts["in"]).dt.total_seconds()
    firsts["seq"] = firsts.station_id.map(seq)
    prev = firsts[["order_id", "seq", "out"]].rename(columns={"out": "prev_out"})
    prev["seq"] = prev["seq"] + 1  # previous station's OUT read aligns with this station's IN read
    firsts = firsts.merge(prev, on=["order_id", "seq"], how="left")
    firsts["wait_s"] = (firsts["in"] - firsts["prev_out"]).dt.total_seconds()
    width = pd.Timedelta(minutes=bucket_minutes)
    rows = []
    for b in buckets:
        sel = firsts[(firsts["out"] >= b) & (firsts["out"] < b + width)]
        for station, g in sel.groupby("station_id"):
            rows.append({"bucket": b, "station_id": station, "parts": int(len(g)),
                         "avg_dwell_s": float(g.dwell_s.mean()),
                         "avg_wait_before_s": float(g.wait_s.mean()) if g.wait_s.notna().any() else None})
    return pd.DataFrame(rows, columns=["bucket", "station_id", "parts", "avg_dwell_s", "avg_wait_before_s"])


def line_kpis(events: pd.DataFrame, st_kpis: pd.DataFrame, leads: pd.DataFrame, stations: pd.DataFrame,
              buckets: list[pd.Timestamp], bucket_minutes: int) -> pd.DataFrame:
    width = pd.Timedelta(minutes=bucket_minutes)
    bottleneck = stations.sort_values("ideal_cycle_s").station_id.iloc[-1]
    done = events[events.event_type == "order_completed"]
    released = events[events.event_type == "order_released"]
    rows = []
    for b in buckets:
        sk = st_kpis[st_kpis.bucket == b] if not st_kpis.empty else st_kpis
        if sk.empty:
            continue
        d = done[(done.ts >= b) & (done.ts < b + width)]
        good, completed = int((d.result == "good").sum()), int(len(d))
        planned = float(sk.planned_s.max())
        bn = sk[sk.station_id == bottleneck]
        lt = leads[(leads.completed_at >= b) & (leads.completed_at < b + width)] if not leads.empty else leads
        t_end = b + width
        wip = int(released[released.ts < t_end].order_id.nunique() - done[done.ts < t_end].order_id.nunique())
        rows.append({
            "bucket": b, "completed_count": completed, "good_count": good, "scrap_count": completed - good,
            "first_pass_yield": good / completed if completed else None,
            "throughput_per_hour": good / (planned / 3600) if planned > 0 else None,
            "line_oee": float(bn.oee.iloc[0]) if len(bn) and pd.notna(bn.oee.iloc[0]) else None,
            "bottleneck_station": bottleneck,
            "avg_lead_time_s": float(lt.lead_time_s.mean()) if len(lt) else None,
            "wip_end": max(wip, 0),
        })
    return pd.DataFrame(rows)


def to_utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def lookback_start(now: pd.Timestamp, hours: int) -> pd.Timestamp:
    return now - timedelta(hours=hours)
