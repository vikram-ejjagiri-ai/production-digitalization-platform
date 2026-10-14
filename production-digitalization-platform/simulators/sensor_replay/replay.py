"""The "live machine": replays Part 2 of the dataset over MQTT.

Each row is published with the CURRENT wall-clock time (`ts`) plus its original
dataset time (`source_ts`). Downstream services cannot tell this apart from a
real PLC / IoT gateway, so the replay could later be swapped for a real machine
without changing anything else.

REPLAY_SPEED=60 means one hour of machine data is streamed per real minute.
"""
import json
import time
from datetime import datetime, timezone

import pandas as pd

from common import config
from common.features import ALL_SENSORS
from common.log import get_logger
from common.mqtt import make_client, publish_json

log = get_logger("sensor-replay")
SPLIT = config.DATA_DIR / "split"


def resolve_start(df: pd.DataFrame) -> pd.Timestamp:
    if config.LIVE_START not in ("", "auto", "start"):
        return pd.Timestamp(config.LIVE_START)
    if config.LIVE_START == "auto":
        failures = json.loads((SPLIT / "failures.json").read_text())
        first = [pd.Timestamp(f["start"]) for f in failures if pd.Timestamp(f["start"]) > df.timestamp.min()]
        if first:
            return max(df.timestamp.min(), min(first) - pd.Timedelta(hours=12))
    return df.timestamp.min()


def main() -> None:
    log.info("Loading live data (Part 2) ...")
    df = pd.read_csv(SPLIT / "part2_live.csv", parse_dates=["timestamp"])
    start = resolve_start(df)
    df = df[df.timestamp >= start].reset_index(drop=True)
    log.info("Replaying %s rows from %s at %.0fx speed", len(df), start, config.REPLAY_SPEED)

    client = make_client("sensor-replay")
    client.loop_start()
    sensor_topic = config.topic(config.MACHINE_ID, "sensors")
    status_topic = config.topic(config.MACHINE_ID, "replay_status")

    values = df[ALL_SENSORS].to_numpy(dtype="float64").round(4)  # numpy array: low memory even for 1.5 M rows
    stamps = df.timestamp.tolist()
    max_gap = pd.Timedelta(seconds=60)  # recording gaps in the dataset are compressed, not waited out
    while True:
        t_wall0, data_elapsed = time.monotonic(), 0.0
        for i, stamp in enumerate(stamps):
            if i:
                data_elapsed += min(stamp - stamps[i - 1], max_gap).total_seconds()
            delay = t_wall0 + data_elapsed / config.REPLAY_SPEED - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            payload = {
                "machine_id": config.MACHINE_ID,
                "ts": datetime.now(timezone.utc).isoformat(),
                "source_ts": stamp.isoformat(),
                **dict(zip(ALL_SENSORS, values[i].tolist())),
            }
            publish_json(client, sensor_topic, payload)
            if i % 360 == 0:
                publish_json(client, status_topic, {
                    "source_ts": stamp.isoformat(), "progress_pct": round(100 * i / len(stamps), 2),
                    "speed": config.REPLAY_SPEED}, retain=True)
                log.info("Dataset time %s (%.1f%%)", stamp, 100 * i / len(stamps))
        if not config.REPLAY_LOOP:
            log.info("Replay finished.")
            break
        log.info("End of live data reached - restarting replay.")


if __name__ == "__main__":
    main()
