"""Synthetic air-compressor data in the MetroPT-3 format.

Used only as an offline fallback when the real dataset cannot be downloaded. It
reproduces the physics of the Air Production Unit closely enough for the
pipeline to behave the same way: pressure builds while the compressor is loaded,
falls while air is consumed, and an air leak makes the compressor cycle more
often and run hotter.
"""
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from pipeline.data_prep.failures import FAILURES

START_P, STOP_P = 8.2, 10.0
STEP_S = 10


def _leak_intensity(ts: datetime, windows: list[tuple[datetime, datetime]]) -> float:
    """0 = healthy, 1 = full leak. Degradation ramps in over 12 h before the reported start."""
    for start, end in windows:
        ramp_start = start - timedelta(hours=12)
        if ramp_start <= ts < start:
            return 0.6 * (ts - ramp_start) / (start - ramp_start)
        if start <= ts <= end:
            return 1.0
    return 0.0


def generate(start: str = "2020-02-01", end: str = "2020-06-10", seed: int = 7) -> pd.DataFrame:
    rng = random.Random(seed)
    windows = [(pd.Timestamp(f["start"]).to_pydatetime(), pd.Timestamp(f["end"]).to_pydatetime()) for f in FAILURES]
    t0, t1 = pd.Timestamp(start).to_pydatetime(), pd.Timestamp(end).to_pydatetime()
    n = int((t1 - t0).total_seconds() // STEP_S)

    cols = {k: np.zeros(n, dtype=np.float32) for k in [
        "TP2", "TP3", "H1", "DV_pressure", "Reservoirs", "Oil_temperature", "Motor_current",
        "COMP", "DV_eletric", "Towers", "MPG", "LPS", "Pressure_switch", "Oil_level", "Caudal_impulses"]}
    stamps = [t0 + timedelta(seconds=i * STEP_S) for i in range(n)]

    p, temp, state, offload_left, run_steps, towers, cycles = 9.0, 58.0, "off", 0, 0, 0, 0
    demand = 0.015
    for i, ts in enumerate(stamps):
        if i % 360 == 0:  # demand changes every hour (train schedule)
            hour = ts.hour
            base = 0.006 if hour < 5 else 0.016
            demand = base * rng.uniform(0.7, 1.3)
        leak = _leak_intensity(ts, windows)
        consumption = demand + 0.04 * leak + rng.gauss(0, 0.002)

        if state == "off" and p < START_P:
            state, run_steps = "loaded", 0
        if state == "loaded" and p >= STOP_P:
            state, offload_left, cycles = "offload", rng.randint(3, 8), cycles + 1
            if cycles % 4 == 0:
                towers = 1 - towers
        if state == "offload":
            offload_left -= 1
            if offload_left <= 0:
                state = "off"

        if state == "loaded":
            p += 0.045 - consumption * 0.5
            current = 9.0 if run_steps == 0 else 7.0 + rng.gauss(0, 0.15) + 0.9 * leak
            run_steps += 1
            target_t = 74 + 9 * leak
        elif state == "offload":
            p -= consumption
            current = 4.0 + rng.gauss(0, 0.1)
            target_t = 68
        else:
            p -= consumption
            current = max(0.0, rng.gauss(0.03, 0.02))
            target_t = 55
        temp += 0.03 * (target_t - temp) + rng.gauss(0, 0.05)
        p = max(p, 6.0)

        loaded = state == "loaded"
        cols["Reservoirs"][i] = p - 0.02 + rng.gauss(0, 0.01)
        cols["TP3"][i] = p + rng.gauss(0, 0.01)
        cols["TP2"][i] = (p + 0.15 + rng.gauss(0, 0.02)) if loaded else max(0.0, rng.gauss(0.02, 0.01))
        cols["H1"][i] = (p - 0.1 + rng.gauss(0, 0.02)) if loaded else max(0.0, rng.gauss(0.01, 0.01))
        if loaded:
            dv = 0.0
        elif state == "offload":
            dv = 1.8 * offload_left / 8
        else:
            dv = -0.02
        cols["DV_pressure"][i] = dv + rng.gauss(0, 0.005)
        cols["Oil_temperature"][i] = temp
        cols["Motor_current"][i] = current
        cols["COMP"][i] = 0.0 if loaded else 1.0
        cols["DV_eletric"][i] = 1.0 if loaded else 0.0
        cols["Towers"][i] = towers
        cols["MPG"][i] = 1.0 if loaded else 0.0
        cols["LPS"][i] = 1.0 if p < 7.0 else 0.0
        cols["Pressure_switch"][i] = 1.0
        cols["Oil_level"][i] = 1.0
        cols["Caudal_impulses"][i] = 1.0 if loaded else 0.0

    df = pd.DataFrame(cols)
    df.insert(0, "timestamp", pd.to_datetime(stamps))
    return df
