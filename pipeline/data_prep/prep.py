"""Step 1 of the pipeline: get the dataset, clean it, and split it by TIME.

Part 1 (before COMMISSIONING_END) = "commissioning / acceptance test" data used to
learn what healthy looks like. Part 2 = the machine's "live" production data that
the replay service streams over MQTT. Splitting by time (never randomly) avoids
leaking future information into training.

Runs once; skipped automatically when the split already exists.
"""
import json
import os
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import requests

from common import config
from common.features import ALL_SENSORS
from common.log import get_logger
from pipeline.data_prep.failures import FAILURES

log = get_logger("data-prep")

UCI_URL = "https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip"
RAW_DIR = config.DATA_DIR / "raw"
SPLIT_DIR = config.DATA_DIR / "split"

RENAME = {
    "TP2": "tp2", "TP3": "tp3", "H1": "h1", "DV_pressure": "dv_pressure", "Reservoirs": "reservoirs",
    "Oil_temperature": "oil_temperature", "Motor_current": "motor_current", "COMP": "comp",
    "DV_eletric": "dv_electric", "Towers": "towers", "MPG": "mpg", "LPS": "lps",
    "Pressure_switch": "pressure_switch", "Oil_level": "oil_level", "Caudal_impulses": "caudal_impulses",
}


def find_metropt_csv() -> Path | None:
    for p in RAW_DIR.rglob("*.csv"):
        if "metropt" in p.name.lower() or "aircompressor" in p.name.lower():
            return p
    return None


def download_metropt() -> Path:
    log.info("Downloading MetroPT-3 from UCI (~208 MB, one time only) ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RAW_DIR / "metropt3.zip.part"
    with requests.get(UCI_URL, stream=True, timeout=60) as r, open(zip_path, "wb") as fh:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done, next_mark = 0, 10
        for chunk in r.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if total and done * 100 / total >= next_mark:
                log.info("  %d%% downloaded", next_mark)
                next_mark += 10
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        target = RAW_DIR / Path(name).name
        with zf.open(name) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    zip_path.unlink(missing_ok=True)
    log.info("Saved %s", target)
    return target


def load_raw() -> tuple[pd.DataFrame, str]:
    if config.DATASET == "metropt3":
        path = find_metropt_csv()
        if path is None:
            try:
                path = download_metropt()
            except Exception as exc:  # no internet, UCI down, ...
                (RAW_DIR / "metropt3.zip.part").unlink(missing_ok=True)
                log.warning("Download failed (%s). Falling back to SYNTHETIC data.", exc)
        if path is not None:
            log.info("Reading %s", path)
            return pd.read_csv(path), "metropt3"
    from pipeline.data_prep.synthetic import generate
    log.info("Generating synthetic compressor data (MetroPT-3 format) ...")
    return generate(), "synthetic"


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report = {"rows_in": int(len(df))}
    df = df.drop(columns=[c for c in df.columns if c.lower().startswith("unnamed") or c == "index"], errors="ignore")
    df = df.rename(columns=RENAME)
    missing_cols = [c for c in ALL_SENSORS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Dataset is missing expected columns: {missing_cols}")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[["timestamp"] + ALL_SENSORS]
    report["missing_values"] = int(df.isna().sum().sum())
    df = df.dropna()
    before = len(df)
    df = df.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
    report["duplicate_timestamps_removed"] = int(before - len(df))
    df[ALL_SENSORS] = df[ALL_SENSORS].astype("float32")
    gaps = df["timestamp"].diff().dt.total_seconds()
    report["median_sampling_interval_s"] = float(gaps.median())
    report["gaps_over_5_min"] = int((gaps > 300).sum())
    report["rows_out"] = int(len(df))
    report["time_range"] = [str(df["timestamp"].min()), str(df["timestamp"].max())]
    return df.reset_index(drop=True), report


def main() -> None:
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = SPLIT_DIR / "metadata.json"
    force = os.environ.get("FORCE_PREP", "false").lower() == "true"
    if meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text())
        if meta.get("requested_dataset") == config.DATASET and meta.get("commissioning_end") == config.COMMISSIONING_END:
            log.info("Split already exists (%s) - nothing to do.", meta["source"])
            return

    raw, source = load_raw()
    df, quality = clean(raw)
    cut = pd.Timestamp(config.COMMISSIONING_END)
    part1, part2 = df[df["timestamp"] < cut], df[df["timestamp"] >= cut]
    if len(part1) < 1000 or len(part2) < 1000:
        raise ValueError(f"Split at {cut} leaves too little data (part1={len(part1)}, part2={len(part2)})")

    log.info("Part 1 (commissioning): %s rows  %s -> %s", len(part1), part1.timestamp.min(), part1.timestamp.max())
    log.info("Part 2 (live):          %s rows  %s -> %s", len(part2), part2.timestamp.min(), part2.timestamp.max())
    part1.to_csv(SPLIT_DIR / "part1_commissioning.csv", index=False)
    part2.to_csv(SPLIT_DIR / "part2_live.csv", index=False)

    span = (df.timestamp.min(), df.timestamp.max())
    failures = [f for f in FAILURES if span[0] <= pd.Timestamp(f["start"]) <= span[1]]
    (SPLIT_DIR / "failures.json").write_text(json.dumps(failures, indent=2))
    meta = {
        "source": source,
        "requested_dataset": config.DATASET,
        "commissioning_end": config.COMMISSIONING_END,
        "part1_rows": int(len(part1)),
        "part2_rows": int(len(part2)),
        "part1_range": [str(part1.timestamp.min()), str(part1.timestamp.max())],
        "part2_range": [str(part2.timestamp.min()), str(part2.timestamp.max())],
        "data_quality": quality,
        "citation": "Davari, N., Veloso, B., Ribeiro, R., & Gama, J. (2021). MetroPT-3 Dataset. UCI ML Repository. https://doi.org/10.24432/C5VW3R"
        if source == "metropt3" else "Synthetic data generated by pipeline/data_prep/synthetic.py",
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    log.info("Data prep finished. Quality report: %s", quality)


if __name__ == "__main__":
    main()
