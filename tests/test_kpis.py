import pandas as pd
import pytest

from services.kpi_engine import kpis

T0 = pd.Timestamp("2026-01-01 08:00", tz="UTC")
STATIONS = pd.DataFrame({"station_id": ["ST10", "ST20"], "sequence": [1, 2], "ideal_cycle_s": [60.0, 60.0]})


def ev(minute, station, event_type, **kw):
    return {"ts": T0 + pd.Timedelta(minutes=minute), "station_id": station, "event_type": event_type,
            "order_id": kw.get("order_id"), "duration_s": kw.get("duration_s"), "result": kw.get("result"),
            "reason": kw.get("reason")}


def test_oee_textbook_example():
    # 60 min planned, 10 min stop -> availability 50/60.
    # 40 parts x 60 s ideal = 40 min of ideal time in 50 min run -> performance 0.8.
    # 38 good of 40 -> quality 0.95.
    rows = [ev(20, "ST10", "downtime_start", reason="tool_change"),
            ev(30, "ST10", "downtime_end", reason="tool_change", duration_s=600)]
    rows += [ev(1 + i, "ST10", "cycle_end", result="scrap" if i < 2 else "good") for i in range(40)]
    events = pd.DataFrame(rows)
    now = T0 + pd.Timedelta(minutes=60)
    st, reasons = kpis.station_kpis(events, STATIONS.iloc[:1], [T0], 60, now, T0)
    r = st.iloc[0]
    assert r.availability == pytest.approx(50 / 60)
    assert r.performance == pytest.approx(0.8)
    assert r.quality == pytest.approx(0.95)
    assert r.oee == pytest.approx(50 / 60 * 0.8 * 0.95)
    assert r.failures == 1 and r.mttr_s == pytest.approx(600)
    assert reasons.iloc[0].reason == "tool_change" and reasons.iloc[0].downtime_s == pytest.approx(600)


def test_open_downtime_counts_until_now():
    events = pd.DataFrame([ev(50, "ST10", "downtime_start", reason="machine_fault")])
    st, _ = kpis.station_kpis(events, STATIONS.iloc[:1], [T0], 60, T0 + pd.Timedelta(minutes=60), T0)
    assert st.iloc[0].downtime_s == pytest.approx(600)


def test_lead_time_and_flow_from_rfid():
    def read(minute, station, direction):
        return {"ts": T0 + pd.Timedelta(minutes=minute), "epc": "E1", "order_id": "O1",
                "station_id": station, "direction": direction}
    rfid = pd.DataFrame([read(0, "ST10", "in"), read(1, "ST10", "out"), read(4, "ST20", "in"), read(5, "ST20", "out")])
    events = pd.DataFrame([ev(5, "ST20", "order_completed", order_id="O1", result="good")])
    lt = kpis.order_lead_times(rfid, events).iloc[0]
    assert lt.lead_time_s == 300 and lt.value_add_s == 120 and lt.waiting_s == 180
    flow = kpis.station_flow(rfid, STATIONS, [T0], 60)
    st20 = flow[flow.station_id == "ST20"].iloc[0]
    assert st20.avg_dwell_s == 60 and st20.avg_wait_before_s == 180
