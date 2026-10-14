"""Harmonization rules: turn heterogeneous shopfloor messages into one clean format.

Pure functions (no I/O) so they are easy to unit test - see tests/test_harmonize.py.
"""
import re
from datetime import datetime, timezone

from common.features import ALL_SENSORS

KNOWN_STATIONS = {"ST10", "ST20", "ST30", "ST40", "ST50"}
EVENT_TYPES = {"order_released", "cycle_start", "cycle_end", "downtime_start", "downtime_end", "order_completed"}
SENSOR_RANGES = {  # physically plausible ranges; values outside get a data-quality flag
    "tp2": (-1, 20), "tp3": (-1, 20), "h1": (-1, 20), "dv_pressure": (-1, 20), "reservoirs": (-1, 20),
    "oil_temperature": (-20, 130), "motor_current": (-1, 30),
}


class ValidationError(ValueError):
    pass


def canonical_station(raw: str) -> str:
    """'st-20', 'Station_30', 'STATION 40', 'st50' -> 'ST20', 'ST30', 'ST40', 'ST50'."""
    m = re.search(r"(\d{1,3})", str(raw))
    if not m:
        raise ValidationError(f"unknown station id {raw!r}")
    sid = f"ST{int(m.group(1)):02d}"
    if sid not in KNOWN_STATIONS:
        raise ValidationError(f"station {sid} not in master data")
    return sid


def parse_ts(payload: dict) -> datetime:
    if "timestamp_ms" in payload:
        return datetime.fromtimestamp(int(payload["timestamp_ms"]) / 1000, timezone.utc)
    for key in ("timestamp", "ts", "read_time"):
        if key in payload:
            ts = datetime.fromisoformat(str(payload[key]).replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    raise ValidationError("no timestamp field")


def harmonize_event(payload: dict) -> dict:
    event_type = payload.get("event")
    if event_type not in EVENT_TYPES:
        raise ValidationError(f"unknown event type {event_type!r}")
    if "duration_ms" in payload:
        duration = float(payload["duration_ms"]) / 1000.0
    elif "duration_s" in payload:
        duration = float(payload["duration_s"])
    else:
        duration = None
    if duration is not None and duration < 0:
        raise ValidationError("negative duration")
    return {
        "ts": parse_ts(payload),
        "station_id": canonical_station(payload.get("station", "")),
        "event_type": event_type,
        "order_id": payload.get("order_id"),
        "duration_s": duration,
        "result": payload.get("result"),
        "reason": payload.get("reason"),
    }


def parse_reader(reader: str) -> tuple[str, str]:
    """'RDR-ST30-IN' -> ('ST30', 'in')."""
    m = re.match(r"RDR-(\w+?)-(IN|OUT)$", str(reader), re.IGNORECASE)
    if not m:
        raise ValidationError(f"unknown reader {reader!r}")
    return canonical_station(m.group(1)), m.group(2).lower()


def harmonize_rfid(payload: dict) -> dict:
    epc = str(payload.get("epc", "")).upper()
    if not re.fullmatch(r"[0-9A-F]{16,32}", epc):
        raise ValidationError(f"invalid EPC {epc!r}")
    station, direction = parse_reader(payload.get("reader", ""))
    return {
        "ts": parse_ts(payload),
        "epc": epc,
        "order_id": payload.get("order"),
        "station_id": station,
        "direction": direction,
        "rssi": payload.get("rssi"),
    }


class RfidDeduplicator:
    """Drops repeated reads of the same tag at the same reader within `window_s` seconds."""

    def __init__(self, window_s: float = 3.0):
        self.window_s = window_s
        self.last_seen: dict[tuple, datetime] = {}

    def is_duplicate(self, row: dict) -> bool:
        key = (row["epc"], row["station_id"], row["direction"])
        prev = self.last_seen.get(key)
        self.last_seen[key] = row["ts"]
        if len(self.last_seen) > 50_000:  # keep memory bounded
            self.last_seen.clear()
        return prev is not None and abs((row["ts"] - prev).total_seconds()) <= self.window_s


def harmonize_sensor(payload: dict) -> dict:
    if not payload.get("machine_id"):
        raise ValidationError("machine_id missing")
    row = {"ts": parse_ts(payload), "machine_id": payload["machine_id"], "source_ts": payload.get("source_ts")}
    flags = []
    for s in ALL_SENSORS:
        v = payload.get(s)
        if v is None:
            flags.append(f"{s}_missing")
            row[s] = None
            continue
        v = float(v)
        lo, hi = SENSOR_RANGES.get(s, (-0.5, 1.5))
        if not lo <= v <= hi:
            flags.append(f"{s}_out_of_range")
        row[s] = v
    row["dq_flag"] = ",".join(flags) or None
    return row
