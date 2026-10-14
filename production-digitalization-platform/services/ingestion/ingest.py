"""Ingestion service: MQTT -> raw layer -> harmonization -> clean layer.

Every message is stored unchanged in raw.messages (audit trail, can be
re-processed). Valid messages are harmonized and written to the clean tables;
invalid ones go to raw.rejected_messages with the reason. Writes are batched
once per second for throughput.
"""
import json
import queue
import time

from common import config, db
from common.features import ALL_SENSORS
from common.log import get_logger
from common.mqtt import make_client
from services.ingestion.harmonize import (RfidDeduplicator, ValidationError, harmonize_event,
                                          harmonize_rfid, harmonize_sensor)

log = get_logger("ingestion")
inbox: "queue.Queue[tuple[str, bytes]]" = queue.Queue(maxsize=100_000)

SENSOR_COLS = ["ts", "machine_id", "source_ts"] + ALL_SENSORS + ["dq_flag"]
EVENT_COLS = ["ts", "station_id", "event_type", "order_id", "duration_s", "result", "reason"]
RFID_COLS = ["ts", "epc", "order_id", "station_id", "direction", "rssi"]


def on_message(client, userdata, msg):
    try:
        inbox.put_nowait((msg.topic, msg.payload))
    except queue.Full:
        log.warning("Ingestion queue full - dropping message")


def process_batch(conn, batch, dedup: RfidDeduplicator, stats: dict) -> None:
    raw_rows, rejected, sensors, events, rfids = [], [], [], [], []
    for topic, payload_bytes in batch:
        kind = topic.rsplit("/", 1)[-1]
        try:
            payload = json.loads(payload_bytes)
            if not isinstance(payload, dict):
                raise ValidationError("payload is not a JSON object")
        except (ValueError, ValidationError) as exc:
            rejected.append((topic, payload_bytes.decode(errors="replace")[:2000], f"invalid JSON: {exc}"))
            continue
        raw_rows.append((topic, db.json_param(payload)))
        try:
            if kind == "sensors":
                r = harmonize_sensor(payload)
                sensors.append(tuple(r[c] for c in SENSOR_COLS))
            elif kind == "events":
                r = harmonize_event(payload)
                events.append(tuple(r[c] for c in EVENT_COLS))
            elif kind == "rfid":
                r = harmonize_rfid(payload)
                if dedup.is_duplicate(r):
                    stats["rfid_duplicates"] += 1
                else:
                    rfids.append(tuple(r[c] for c in RFID_COLS))
            # alarms / replay_status: raw only (alarms are written by the anomaly service)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            rejected.append((topic, json.dumps(payload)[:2000], str(exc)))

    with db.cursor(conn) as cur:
        db.insert_many(cur, "raw.messages", ["topic", "payload"], raw_rows)
        db.insert_many(cur, "raw.rejected_messages", ["topic", "payload", "error"], rejected)
        db.insert_many(cur, "clean.sensor_readings", SENSOR_COLS, sensors)
        db.insert_many(cur, "clean.line_events", EVENT_COLS, events)
        db.insert_many(cur, "clean.rfid_reads", RFID_COLS, rfids)
    stats["messages"] += len(batch)
    stats["rejected"] += len(rejected)


def main() -> None:
    conn = db.connect()
    client = make_client("ingestion", on_message=on_message, subscriptions=[f"factory/{config.PLANT}/#"])
    client.loop_start()
    dedup = RfidDeduplicator()
    stats = {"messages": 0, "rejected": 0, "rfid_duplicates": 0}
    last_log = time.monotonic()
    log.info("Ingestion running.")
    while True:
        batch = []
        deadline = time.monotonic() + 1.0
        while len(batch) < 5000:
            try:
                batch.append(inbox.get(timeout=max(0.0, deadline - time.monotonic())))
            except queue.Empty:
                break
        if batch:
            try:
                process_batch(conn, batch, dedup, stats)
            except Exception as exc:  # database restarted etc. -> reconnect, keep running
                log.error("Write failed (%s) - reconnecting", exc)
                try:
                    conn.close()
                except Exception:
                    pass
                conn = db.connect()
        if time.monotonic() - last_log > 30:
            log.info("Stats: %s", stats)
            last_log = time.monotonic()


if __name__ == "__main__":
    main()
