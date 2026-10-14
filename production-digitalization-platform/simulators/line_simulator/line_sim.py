"""Discrete-event simulation of a 5-station assembly line (SimPy, real time).

Product: a cabin galley module. Every part carrier has an RFID tag that is read
when it enters and leaves each station. The simulator publishes:

  factory/<plant>/<line>/stNN/events  - order released, cycle start/end, downtime, order completed
  factory/<plant>/<line>/stNN/rfid    - raw RFID tag reads (including realistic duplicate reads)

To make data harmonization a real task (as in a brownfield plant with PLCs from
different vendors), stations deliberately report in different formats:
  * station ids:   "ST10", "st-20", "Station_30", "STATION 40", "st50"
  * durations:     ST10/ST20 send milliseconds, the others seconds
  * timestamps:    ST10/ST20 send epoch milliseconds, the others ISO-8601

Station ST30 (panel bonding) uses compressed air from the compressor. When the
anomaly service raises a compressor alarm, ST30 slows down, produces more
scrap and stops more often for "low_air_pressure" - linking machine health to
production KPIs.
"""
import json
import math
import random
import threading
from datetime import datetime, timezone

import simpy
import simpy.rt

from common import config
from common.log import get_logger
from common.mqtt import make_client, publish_json

log = get_logger("line-simulator")
rng = random.Random(11)

STATIONS = [
    # canonical, raw id sent by the "PLC", ideal cycle [s], scrap prob, uses air, ms-format?
    {"id": "ST10", "raw": "ST10", "name": "Kitting", "cycle": 40, "scrap": 0.003, "air": False, "legacy": True},
    {"id": "ST20", "raw": "st-20", "name": "Frame assembly", "cycle": 60, "scrap": 0.008, "air": False, "legacy": True},
    {"id": "ST30", "raw": "Station_30", "name": "Panel bonding", "cycle": 75, "scrap": 0.015, "air": True, "legacy": False},
    {"id": "ST40", "raw": "STATION 40", "name": "Electrical installation", "cycle": 55, "scrap": 0.010, "air": False, "legacy": False},
    {"id": "ST50", "raw": "st50", "name": "Final inspection", "cycle": 45, "scrap": 0.025, "air": False, "legacy": False},
]
DOWNTIME_REASONS = {
    "material_missing": 0.35, "tool_change": 0.2, "machine_fault": 0.2,
    "quality_check": 0.15, "operator_absent": 0.1,
}
MTBF_S = 30 * 60      # mean run time between stops
MTTR_S = 3 * 60       # mean repair time
BUFFER_SIZE = 3
WIP_LIMIT = 12
RELEASE_MEAN_S = 70

state = {"air_degraded": False}


class Line:
    def __init__(self, env: simpy.Environment, client):
        self.env, self.client = env, client
        self.buffers = [simpy.Store(env, capacity=BUFFER_SIZE) for _ in STATIONS]
        self.wip = 0
        self.order_seq = 0

    # ---------------- publishing helpers (deliberately heterogeneous formats) ----------------
    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def _event(self, st: dict, event_type: str, **fields) -> None:
        now = self._now()
        payload = {"station": st["raw"], "event": event_type}
        if "duration_s" in fields:  # report wall-clock seconds so durations match timestamps
            fields["duration_s"] = round(fields["duration_s"] / config.LINE_TIME_SCALE, 2)
        if st["legacy"]:
            payload["timestamp_ms"] = int(now.timestamp() * 1000)
            if "duration_s" in fields:
                fields["duration_ms"] = int(fields.pop("duration_s") * 1000)
        else:
            payload["timestamp"] = now.isoformat()
        payload.update({k: v for k, v in fields.items() if v is not None})
        publish_json(self.client, config.topic(st["id"].lower(), "events"), payload)

    def _rfid(self, st: dict, part: dict, direction: str) -> None:
        reader = f"RDR-{st['id']}-{'IN' if direction == 'in' else 'OUT'}"
        reads = 2 if rng.random() < 0.15 else 1  # tags are often read twice by the antenna
        for n in range(reads):
            ts = self._now().timestamp() + n * rng.uniform(0.2, 1.5)
            payload = {
                "epc": part["epc"], "reader": reader, "antenna": rng.choice([1, 2]),
                "rssi": round(rng.uniform(-68, -42), 1),
                "read_time": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                "order": part["order_id"],
            }
            publish_json(self.client, config.topic(st["id"].lower(), "rfid"), payload)

    # ---------------- processes ----------------
    def release(self):
        st = STATIONS[0]
        while True:
            yield self.env.timeout(rng.expovariate(1 / RELEASE_MEAN_S))
            while self.wip >= WIP_LIMIT:
                yield self.env.timeout(5)
            self.order_seq += 1
            part = {
                "order_id": f"ORD-{datetime.now():%y%m%d}-{self.order_seq:05d}",
                "epc": f"E28011606000{rng.randrange(16**8):08X}",
            }
            self.wip += 1
            self._event(st, "order_released", order_id=part["order_id"])
            yield self.buffers[0].put(part)

    def station(self, idx: int):
        st = STATIONS[idx]
        next_stop = self.env.now + rng.expovariate(1 / MTBF_S)
        next_air_stop = self.env.now + rng.expovariate(1 / (8 * 60))
        while True:
            part = yield self.buffers[idx].get()
            self._rfid(st, part, "in")

            # unplanned stops happen between cycles
            if self.env.now >= next_stop:
                reason = rng.choices(list(DOWNTIME_REASONS), weights=DOWNTIME_REASONS.values())[0]
                yield from self._downtime(st, reason)
                next_stop = self.env.now + rng.expovariate(1 / MTBF_S)
            if st["air"] and state["air_degraded"] and self.env.now >= next_air_stop:
                yield from self._downtime(st, "low_air_pressure")
                next_air_stop = self.env.now + rng.expovariate(1 / (8 * 60))

            factor = 1.3 if (st["air"] and state["air_degraded"]) else 1.0
            cycle = st["cycle"] * factor * math.exp(rng.gauss(0.04, 0.08))
            self._event(st, "cycle_start", order_id=part["order_id"])
            yield self.env.timeout(cycle)
            scrap_p = st["scrap"] * (6 if factor > 1 else 1)
            result = "scrap" if rng.random() < scrap_p else "good"
            self._event(st, "cycle_end", order_id=part["order_id"], duration_s=round(cycle, 2), result=result)

            if result == "scrap":
                self._rfid(st, part, "out")
                self._event(st, "order_completed", order_id=part["order_id"], result="scrap")
                self.wip -= 1
                continue
            if idx + 1 < len(STATIONS):
                yield self.buffers[idx + 1].put(part)  # blocks while the next buffer is full
                self._rfid(st, part, "out")
            else:
                self._rfid(st, part, "out")
                self._event(st, "order_completed", order_id=part["order_id"], result="good")
                self.wip -= 1

    def _downtime(self, st: dict, reason: str):
        duration = rng.lognormvariate(math.log(MTTR_S), 0.6)
        if reason == "low_air_pressure":
            duration *= 0.7
        self._event(st, "downtime_start", reason=reason)
        yield self.env.timeout(duration)
        self._event(st, "downtime_end", reason=reason, duration_s=round(duration, 1))


def on_alarm(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        degraded = payload.get("state") == "open"
        if degraded != state["air_degraded"]:
            state["air_degraded"] = degraded
            log.info("Compressor alarm %s -> ST30 air supply %s", payload.get("state"),
                     "DEGRADED" if degraded else "normal")
    except (ValueError, AttributeError):
        pass


def main() -> None:
    client = make_client("line-simulator", on_message=on_alarm,
                         subscriptions=[config.topic(config.MACHINE_ID, "alarms")])
    threading.Thread(target=client.loop_forever, daemon=True).start()

    env = simpy.rt.RealtimeEnvironment(factor=1.0 / config.LINE_TIME_SCALE, strict=False)
    line = Line(env, client)
    env.process(line.release())
    for i in range(len(STATIONS)):
        env.process(line.station(i))
    log.info("Assembly line running: %s", " -> ".join(s["id"] for s in STATIONS))
    env.run()


if __name__ == "__main__":
    main()
