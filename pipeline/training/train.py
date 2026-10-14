"""Step 2 of the pipeline: "commissioning analysis" on Part 1.

1. Learns the machine's healthy fingerprint (window features, SPC limits).
2. Trains an Isolation Forest health model on Part 1 only.
3. Evaluates it on Part 2 against the published failure reports
   (detection rate, early-warning lead time, false alarms per week).
4. Writes models/health_model.joblib, models/machine_profile.json and an HTML
   commissioning report to reports/.

Runs once; skipped when a model for the current data split already exists.
"""
import base64
import io
import json
import math
import os
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import config  # noqa: E402
from common.alarm import ALARM_BELOW, AlarmTracker  # noqa: E402
from common.features import ANALOG, UNITS, sliding_features  # noqa: E402
from common.health import HealthModel  # noqa: E402
from common.log import get_logger  # noqa: E402

log = get_logger("trainer")
SPLIT = config.DATA_DIR / "split"
EVAL_STRIDE = 30  # evaluate every 30 rows (~5 min of machine time) to keep it fast


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(SPLIT / name, parse_dates=["timestamp"])


def evaluate(model: HealthModel, part2: pd.DataFrame, failures: list[dict]) -> tuple[dict, pd.DataFrame]:
    feats, ts = sliding_features(part2, config.WINDOW_ROWS, EVAL_STRIDE)
    health = model.health(feats.to_numpy())
    scale = config.STEP_ROWS / EVAL_STRIDE
    tracker = AlarmTracker(max(1, round(config.ALARM_PERSIST * scale)), max(1, round(config.CLEAR_PERSIST * scale)))
    alarms, current = [], None
    for t, h in zip(ts, health):
        change = tracker.update(float(h))
        if change == "open":
            current = {"open": t}
        elif change == "close" and current:
            current["close"] = t
            alarms.append(current)
            current = None
    if current:
        current["close"] = ts.iloc[-1]
        alarms.append(current)

    horizon = pd.Timedelta(hours=48)
    results, matched = [], set()
    for f in failures:
        start, end = pd.Timestamp(f["start"]), pd.Timestamp(f["end"])
        hits = [i for i, a in enumerate(alarms) if start - horizon <= a["open"] <= end]
        matched.update(hits)
        first = alarms[hits[0]]["open"] if hits else None
        results.append({
            **f,
            "detected": bool(hits),
            "first_alarm": str(first) if first is not None else None,
            "lead_time_hours": round((start - first).total_seconds() / 3600, 1) if first is not None else None,
        })
    false_alarms = [a for i, a in enumerate(alarms) if i not in matched]
    weeks = max((ts.iloc[-1] - ts.iloc[0]).total_seconds() / (7 * 86400), 1e-9)
    summary = {
        "failures_in_live_data": len(failures),
        "failures_detected": sum(r["detected"] for r in results),
        "false_alarms": len(false_alarms),
        "false_alarms_per_week": round(len(false_alarms) / weeks, 2),
        "total_alarms": len(alarms),
        "per_failure": results,
        "note": "An alarm counts as a detection if it opens up to 48 h before or during a reported failure.",
    }
    curve = pd.DataFrame({"timestamp": ts, "health": health})
    return summary, curve


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def build_report(part1, part2, curve, failures, evaluation, model, meta) -> str:
    imgs = []
    fig, axes = plt.subplots(2, 4, figsize=(15, 6))
    for ax, s in zip(axes.flat, ANALOG):
        ax.hist(part1[s], bins=60, color="#534AB7", alpha=0.85)
        ax.set_title(f"{s} [{UNITS[s]}]", fontsize=10)
    axes.flat[-1].axis("off")
    fig.suptitle("Part 1 (commissioning): sensor distributions")
    imgs.append(("Healthy operating ranges", fig_to_b64(fig)))

    sample = part1.iloc[: 6 * 360]
    fig, axes = plt.subplots(3, 1, figsize=(15, 7), sharex=True)
    for ax, s in zip(axes, ["reservoirs", "motor_current", "oil_temperature"]):
        ax.plot(sample.timestamp, sample[s], lw=0.8, color="#0F6E56")
        ax.set_ylabel(f"{s}\n[{UNITS[s]}]")
    fig.suptitle("Part 1: six hours of normal compressor load/unload cycles")
    imgs.append(("Normal operating cycle", fig_to_b64(fig)))

    fig, ax = plt.subplots(figsize=(15, 4))
    ax.plot(curve.timestamp, curve.health, lw=0.6, color="#185FA5")
    ax.axhline(ALARM_BELOW, color="#A32D2D", ls="--", lw=1, label="alarm threshold")
    for f in failures:
        ax.axvspan(pd.Timestamp(f["start"]), pd.Timestamp(f["end"]), color="#E24B4A", alpha=0.25)
    ax.set_ylim(0, 105)
    ax.set_ylabel("health score")
    ax.legend(loc="lower left")
    ax.set_title("Part 2 (live): health score vs. reported failures (red bands)")
    imgs.append(("Health score on unseen live data", fig_to_b64(fig)))

    if failures:
        f = failures[0]
        a, b = pd.Timestamp(f["start"]) - pd.Timedelta(hours=36), pd.Timestamp(f["end"]) + pd.Timedelta(hours=6)
        win = part2[(part2.timestamp >= a) & (part2.timestamp <= b)]
        cw = curve[(curve.timestamp >= a) & (curve.timestamp <= b)]
        fig, axes = plt.subplots(3, 1, figsize=(15, 7), sharex=True)
        axes[0].plot(win.timestamp, win.reservoirs, lw=0.5, color="#0F6E56")
        axes[0].set_ylabel("reservoirs [bar]")
        axes[1].plot(win.timestamp, win.motor_current, lw=0.5, color="#854F0B")
        axes[1].set_ylabel("motor current [A]")
        axes[2].plot(cw.timestamp, cw.health, color="#185FA5")
        axes[2].axhline(ALARM_BELOW, color="#A32D2D", ls="--", lw=1)
        axes[2].set_ylabel("health")
        for ax in axes:
            ax.axvspan(pd.Timestamp(f["start"]), pd.Timestamp(f["end"]), color="#E24B4A", alpha=0.2)
        fig.suptitle(f"Zoom on failure #{f['id']} ({f['type']})")
        imgs.append((f"Failure #{f['id']} close-up", fig_to_b64(fig)))

    stats = part1[ANALOG].describe().T[["mean", "std", "min", "max"]].round(3)
    rows = "".join(
        f"<tr><td>{s}</td><td>{UNITS[s]}</td><td>{r['mean']}</td><td>{r['std']}</td><td>{r['min']}</td><td>{r['max']}</td></tr>"
        for s, r in stats.iterrows()
    )
    per_fail = "".join(
        f"<tr><td>#{r['id']}</td><td>{r['type']}</td><td>{r['start']}</td><td>{'yes' if r['detected'] else 'no'}</td>"
        f"<td>{r['lead_time_hours'] if r['lead_time_hours'] is not None else '-'}</td></tr>"
        for r in evaluation["per_failure"]
    )
    figures = "".join(f"<h3>{t}</h3><img src='data:image/png;base64,{b}'/>" for t, b in imgs)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Commissioning report</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222}}
table{{border-collapse:collapse;margin:1rem 0}}td,th{{border:1px solid #ccc;padding:4px 10px;text-align:right}}
td:first-child,th:first-child{{text-align:left}}img{{max-width:100%}}.k{{display:inline-block;margin:0 2rem 1rem 0}}
.k b{{display:block;font-size:1.8rem}}</style></head><body>
<h1>Commissioning report: {config.MACHINE_ID}</h1>
<p>Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Data source: <b>{meta['source']}</b>.
Part 1: {meta['part1_range'][0]} to {meta['part1_range'][1]} ({meta['part1_rows']:,} rows).
Part 2: {meta['part2_range'][0]} to {meta['part2_range'][1]} ({meta['part2_rows']:,} rows).</p>
<div class="k"><b>{evaluation['failures_detected']}/{evaluation['failures_in_live_data']}</b>failures detected</div>
<div class="k"><b>{evaluation['false_alarms_per_week']}</b>false alarms / week</div>
<div class="k"><b>{len(model.features)}</b>window features</div>
<h2>Healthy baseline (Part 1)</h2><table><tr><th>sensor</th><th>unit</th><th>mean</th><th>std</th><th>min</th><th>max</th></tr>{rows}</table>
<h2>Evaluation on live data (Part 2)</h2>
<table><tr><th>failure</th><th>type</th><th>reported start</th><th>detected</th><th>early warning [h]</th></tr>{per_fail}</table>
<p>{evaluation['note']}</p>{figures}
<p style="color:#666">{meta['citation']}</p></body></html>"""


def main() -> None:
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    meta = json.loads((SPLIT / "metadata.json").read_text())
    signature = {"source": meta["source"], "commissioning_end": meta["commissioning_end"],
                 "window_rows": config.WINDOW_ROWS}
    profile_path = config.MODEL_DIR / "machine_profile.json"
    model_path = config.MODEL_DIR / "health_model.joblib"
    if profile_path.exists() and model_path.exists() and os.environ.get("FORCE_TRAIN", "false").lower() != "true":
        if json.loads(profile_path.read_text()).get("signature") == signature:
            log.info("Model for this data split already exists - skipping training.")
            return

    part1, part2 = load_csv("part1_commissioning.csv"), load_csv("part2_live.csv")
    failures = json.loads((SPLIT / "failures.json").read_text())
    failures = [f for f in failures if pd.Timestamp(f["start"]) >= part2.timestamp.min()]

    log.info("Computing window features on Part 1 (%s rows) ...", len(part1))
    feats, _ = sliding_features(part1, config.WINDOW_ROWS, config.STEP_ROWS)
    log.info("Training health model on %s windows ...", len(feats))
    model = HealthModel.fit(feats.to_numpy())

    log.info("Evaluating on Part 2 (%s rows) ...", len(part2))
    evaluation, curve = evaluate(model, part2, failures)
    log.info("Detected %s/%s failures, %s false alarms/week",
             evaluation["failures_detected"], evaluation["failures_in_live_data"], evaluation["false_alarms_per_week"])

    model.meta = {"trained_at": datetime.now(timezone.utc).isoformat(), **signature}
    model.save(model_path)
    raw_limits = {
        s: {"p01": float(np.percentile(part1[s], 1)), "p99": float(np.percentile(part1[s], 99)),
            "mean": float(part1[s].mean()), "std": float(part1[s].std()), "unit": UNITS[s]}
        for s in ANALOG
    }
    profile = {
        "machine_id": config.MACHINE_ID,
        "signature": signature,
        "trained_at": model.meta["trained_at"],
        "window_rows": config.WINDOW_ROWS,
        "step_rows": config.STEP_ROWS,
        "sensor_ranges": raw_limits,
        "feature_control_limits": model.control_limits(),
        "evaluation": evaluation,
    }
    profile_path.write_text(json.dumps(profile, indent=2, default=str))
    (config.REPORT_DIR / "model_evaluation.json").write_text(json.dumps(evaluation, indent=2, default=str))
    html = build_report(part1, part2, curve, failures, evaluation, model, meta)
    (config.REPORT_DIR / "commissioning_report.html").write_text(html)
    log.info("Saved model, profile and reports/commissioning_report.html")


if __name__ == "__main__":
    main()
