"""Feature engineering shared by training (offline) and anomaly detection (live).

Using the *same* code in both places avoids training/serving skew, a classic
production-ML bug. Features are computed over a sliding window of raw readings.
"""
import numpy as np
import pandas as pd

ANALOG = ["tp2", "tp3", "h1", "dv_pressure", "reservoirs", "oil_temperature", "motor_current"]
DIGITAL = ["comp", "dv_electric", "towers", "mpg", "lps", "pressure_switch", "oil_level", "caudal_impulses"]
ALL_SENSORS = ANALOG + DIGITAL

UNITS = {
    "tp2": "bar", "tp3": "bar", "h1": "bar", "dv_pressure": "bar", "reservoirs": "bar",
    "oil_temperature": "°C", "motor_current": "A",
}

LOADED_CURRENT_A = 6.0  # motor current above this = compressor working under load
STATS = ("mean", "std", "min", "max")


def feature_names() -> list[str]:
    names = [f"{s}_{stat}" for s in ANALOG for stat in STATS]
    return names + ["duty_loaded", "load_cycles"]


def sensor_of(feature: str) -> str:
    for s in ANALOG:
        if feature.startswith(s + "_"):
            return s
    return "motor_current"  # duty_loaded / load_cycles are derived from motor current


def window_features(window: np.ndarray) -> np.ndarray:
    """window: shape (rows, len(ANALOG)) -> 1-D feature vector."""
    return batch_features(window[None, :, :])[0]


def batch_features(windows: np.ndarray) -> np.ndarray:
    """windows: shape (n_windows, rows, len(ANALOG)) -> (n_windows, n_features)."""
    mean = windows.mean(axis=1)
    std = windows.std(axis=1)
    mn = windows.min(axis=1)
    mx = windows.max(axis=1)
    per_sensor = np.stack([mean, std, mn, mx], axis=2).reshape(len(windows), -1)
    current = windows[:, :, ANALOG.index("motor_current")]
    loaded = (current > LOADED_CURRENT_A).astype(np.int8)
    duty = loaded.mean(axis=1, keepdims=True)
    cycles = (np.diff(loaded, axis=1) > 0).sum(axis=1, keepdims=True).astype(float)
    return np.hstack([per_sensor, duty, cycles])


def sliding_features(df: pd.DataFrame, window_rows: int, stride: int) -> tuple[pd.DataFrame, pd.Series]:
    """Compute features for every `stride`-th full window. Returns (features, window_end_timestamps)."""
    arr = df[ANALOG].to_numpy(dtype=np.float32)
    if len(arr) < window_rows:
        return pd.DataFrame(columns=feature_names()), pd.Series(dtype="datetime64[ns]")
    view = np.lib.stride_tricks.sliding_window_view(arr, window_rows, axis=0)  # (n, sensors, rows)
    view = view[::stride].transpose(0, 2, 1)
    out = []
    for start in range(0, len(view), 5000):  # chunk to keep memory low
        out.append(batch_features(np.ascontiguousarray(view[start:start + 5000])))
    feats = np.vstack(out)
    end_idx = np.arange(window_rows - 1, len(arr), stride)[: len(feats)]
    ts = df["timestamp"].iloc[end_idx].reset_index(drop=True)
    return pd.DataFrame(feats, columns=feature_names()), ts
