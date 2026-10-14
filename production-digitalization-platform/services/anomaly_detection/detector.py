"""Streaming anomaly detection: scores every new window of live sensor data.

Subscribes directly to the sensor topic (stream processing - no database
round trip), keeps a sliding window in memory, and every STEP_ROWS readings:
  1. computes the same features used in training (common/features.py)
  2. scores them with the health model trained on Part 1
  3. updates the alarm state machine (persistence + hysteresis)
  4. writes health + alarms to the database and publishes alarm state on MQTT
"""
import json
import queue
from collections import deque
from datetime import datetime, timezone

import numpy as np

from common import config, db
from common.alarm import AlarmTracker, status_of
from common.features import ANALOG, feature_names, window_features
from common.health import HealthModel
from common.log import get_logger
from common.mqtt import make_client, publish_json

log = get_logger("anomaly-detection")
inbox: "queue.Queue[dict]" = queue.Queue(maxsize=50_000)


def on_message(client, userdata, msg):
    try:
        inbox.put_nowait(json.loads(msg.payload))
    except (ValueError, queue.Full):
        pass


def write_limits(conn, profile: dict) -> None:
    """Publish the commissioning limits so dashboards can draw them as bands."""
    rows = [(config.MACHINE_ID, s, r["unit"], r["p01"], r["mean"], r["p99"])
            for s, r in profile["sensor_ranges"].items()]
    with db.cursor(conn) as cur:
        db.insert_many(cur, "kpi.sensor_limits",
                       ["machine_id", "sensor", "unit", "lower_limit", "center", "upper_limit"], rows,
                       on_conflict="ON CONFLICT (machine_id, sensor) DO UPDATE SET lower_limit = EXCLUDED.lower_limit, "
                                   "center = EXCLUDED.center, upper_limit = EXCLUDED.upper_limit, unit = EXCLUDED.unit")


def restore_open_alarm(conn) -> int | None:
    with db.cursor(conn) as cur:
        cur.execute("SELECT alarm_id FROM clean.alarms WHERE machine_id = %s AND status = 'open' "
                    "ORDER BY opened_at DESC LIMIT 1", (config.MACHINE_ID,))
        row = cur.fetchone()
    return row[0] if row else None


def main() -> None:
    model = HealthModel.load(config.MODEL_DIR / "health_model.joblib")
    profile = json.loads((config.MODEL_DIR / "machine_profile.json").read_text())
    assert model.features == feature_names(), "model was trained with a different feature set"
    conn = db.connect()
    write_limits(conn, profile)

    client = make_client("anomaly-detection", on_message=on_message,
                         subscriptions=[config.topic(config.MACHINE_ID, "sensors")])
    client.loop_start()
    alarm_topic = config.topic(config.MACHINE_ID, "alarms")

    window: deque = deque(maxlen=config.WINDOW_ROWS)
    tracker = AlarmTracker(config.ALARM_PERSIST, config.CLEAR_PERSIST)
    open_alarm_id = restore_open_alarm(conn)
    tracker.active = open_alarm_id is not None
    publish_json(client, alarm_topic, {"state": "open" if tracker.active else "close",
                                        "machine_id": config.MACHINE_ID}, retain=True)
    min_health, since_step = 100.0, 0
    log.info("Anomaly detection running (window=%s rows, step=%s rows).", config.WINDOW_ROWS, config.STEP_ROWS)

    while True:
        msg = inbox.get()
        try:
            window.append([float(msg[s]) for s in ANALOG])
        except (KeyError, TypeError, ValueError):
            continue
        since_step += 1
        if len(window) < config.WINDOW_ROWS or since_step < config.STEP_ROWS:
            continue
        since_step = 0

        x = window_features(np.asarray(window, dtype=np.float32))
        model_features = x[None, :]
        h_forest = float(model.health_forest(model_features)[0])
        h_z = float(model.health_zscore(model_features)[0])
        health = (h_forest + h_z) / 2
        contributors = model.contributors(x)
        change = tracker.update(health)
        status = status_of(health, tracker.active)
        now = datetime.now(timezone.utc)
        source_ts = msg.get("source_ts")

        try:
            with db.cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO clean.machine_health (ts, machine_id, source_ts, health_score, health_forest, "
                    "health_zscore, status, contributors) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (now, config.MACHINE_ID, source_ts, health, h_forest, h_z, status, db.json_param(contributors)))
                if change == "open":
                    min_health = health
                    cur.execute(
                        "INSERT INTO clean.alarms (machine_id, opened_at, source_ts_open, min_health, contributors) "
                        "VALUES (%s,%s,%s,%s,%s) RETURNING alarm_id",
                        (config.MACHINE_ID, now, source_ts, health, db.json_param(contributors)))
                    open_alarm_id = cur.fetchone()[0]
                elif tracker.active and open_alarm_id:
                    if health < min_health:
                        min_health = health
                        cur.execute("UPDATE clean.alarms SET min_health = %s, contributors = %s WHERE alarm_id = %s",
                                    (health, db.json_param(contributors), open_alarm_id))
                elif change == "close" and open_alarm_id:
                    cur.execute("UPDATE clean.alarms SET status='closed', closed_at=%s, source_ts_close=%s "
                                "WHERE alarm_id=%s", (now, source_ts, open_alarm_id))
        except Exception as exc:
            log.error("DB write failed (%s) - reconnecting", exc)
            conn = db.connect()
            continue

        if change == "open":
            log.warning("ALARM OPENED #%s health=%.1f dataset_time=%s top=%s", open_alarm_id, health, source_ts,
                        [c["feature"] for c in contributors])
            publish_json(client, alarm_topic, {"state": "open", "alarm_id": open_alarm_id,
                                                "machine_id": config.MACHINE_ID, "health": health,
                                                "contributors": contributors}, retain=True)
        elif change == "close":
            log.info("Alarm #%s closed (dataset_time=%s)", open_alarm_id, source_ts)
            publish_json(client, alarm_topic, {"state": "close", "alarm_id": open_alarm_id,
                                                "machine_id": config.MACHINE_ID}, retain=True)
            open_alarm_id = None


if __name__ == "__main__":
    main()
