from datetime import datetime, timedelta, timezone

import pytest

from services.ingestion.harmonize import (RfidDeduplicator, ValidationError, canonical_station, harmonize_event,
                                          harmonize_rfid, harmonize_sensor, parse_reader)


@pytest.mark.parametrize("raw,expected", [("ST10", "ST10"), ("st-20", "ST20"), ("Station_30", "ST30"),
                                          ("STATION 40", "ST40"), ("st50", "ST50")])
def test_station_ids_are_harmonized(raw, expected):
    assert canonical_station(raw) == expected


def test_unknown_station_is_rejected():
    with pytest.raises(ValidationError):
        canonical_station("ST99")


def test_legacy_event_in_milliseconds_is_converted():
    ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    row = harmonize_event({"station": "st-20", "event": "cycle_end", "timestamp_ms": int(ts.timestamp() * 1000),
                           "duration_ms": 61500, "order_id": "ORD-1", "result": "good"})
    assert row["station_id"] == "ST20"
    assert row["duration_s"] == pytest.approx(61.5)
    assert row["ts"] == ts


def test_modern_event_in_seconds():
    row = harmonize_event({"station": "Station_30", "event": "downtime_end", "timestamp": "2026-01-01T08:00:00+00:00",
                           "duration_s": 120, "reason": "tool_change"})
    assert row["duration_s"] == 120 and row["reason"] == "tool_change"


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValidationError):
        harmonize_event({"station": "ST10", "event": "coffee_break", "timestamp": "2026-01-01T08:00:00+00:00"})


def test_rfid_reader_parsing_and_dedup():
    assert parse_reader("RDR-ST30-IN") == ("ST30", "in")
    base = {"epc": "E28011606000ABCDEF12", "reader": "RDR-ST10-OUT", "read_time": "2026-01-01T08:00:00+00:00"}
    first = harmonize_rfid(base)
    dup = harmonize_rfid({**base, "read_time": "2026-01-01T08:00:01+00:00"})
    later = harmonize_rfid({**base, "read_time": "2026-01-01T08:00:30+00:00"})
    d = RfidDeduplicator(window_s=3)
    assert [d.is_duplicate(first), d.is_duplicate(dup), d.is_duplicate(later)] == [False, True, False]


def test_sensor_out_of_range_is_flagged_not_dropped():
    payload = {"machine_id": "compressor01", "ts": "2026-01-01T08:00:00+00:00", "tp2": 9.1, "tp3": 9.0, "h1": 8.9,
               "dv_pressure": 0, "reservoirs": 9.0, "oil_temperature": 250.0, "motor_current": 7.0, "comp": 0,
               "dv_electric": 1, "towers": 0, "mpg": 1, "lps": 0, "pressure_switch": 1, "oil_level": 1,
               "caudal_impulses": 1}
    row = harmonize_sensor(payload)
    assert row["oil_temperature"] == 250.0
    assert row["dq_flag"] == "oil_temperature_out_of_range"
