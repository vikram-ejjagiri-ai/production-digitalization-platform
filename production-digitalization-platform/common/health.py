"""Machine health model: an ensemble of two detectors on window features.

1. Isolation Forest  - catches unusual *combinations* of features.
2. Max |z-score|     - catches any single feature far outside its commissioning
                       baseline (the multivariate version of an SPC chart).

Both are calibrated on Part 1 so that:  100 = looks like commissioning data,
50 = alarm threshold, 0 = far outside anything seen during commissioning.
The final health score is the average of the two.
"""
from dataclasses import dataclass, field

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from common.features import feature_names, sensor_of


@dataclass
class HealthModel:
    scaler: StandardScaler
    forest: IsolationForest
    features: list[str]
    score_ref_median: float
    score_ref_threshold: float  # score that maps to health 50
    feat_mean: np.ndarray
    feat_std: np.ndarray
    z_median: float = 1.0
    z_threshold: float = 6.0
    meta: dict = field(default_factory=dict)

    @classmethod
    def fit(cls, X: np.ndarray, threshold_percentile: float = 0.5, seed: int = 42) -> "HealthModel":
        scaler = StandardScaler().fit(X)
        Z = scaler.transform(X)
        forest = IsolationForest(n_estimators=200, contamination="auto", random_state=seed, n_jobs=-1).fit(Z)
        scores = forest.decision_function(Z)
        std = X.std(axis=0)
        std[std < 1e-6] = 1e-6
        max_z = np.abs((X - X.mean(axis=0)) / std).max(axis=1)
        return cls(
            scaler=scaler,
            forest=forest,
            features=feature_names(),
            score_ref_median=float(np.median(scores)),
            score_ref_threshold=float(np.percentile(scores, threshold_percentile)),
            feat_mean=X.mean(axis=0),
            feat_std=std,
            z_median=float(np.median(max_z)),
            z_threshold=float(np.percentile(max_z, 99.5)),
        )

    def anomaly_scores(self, X: np.ndarray) -> np.ndarray:
        return self.forest.decision_function(self.scaler.transform(X))

    def health_forest(self, X: np.ndarray) -> np.ndarray:
        s = self.anomaly_scores(X)
        span = max(self.score_ref_median - self.score_ref_threshold, 1e-6)
        # median -> 100, threshold -> 50, threshold - span -> 0
        return np.clip(50.0 + 50.0 * (s - self.score_ref_threshold) / span, 0.0, 100.0)

    def health_zscore(self, X: np.ndarray) -> np.ndarray:
        max_z = np.abs((X - self.feat_mean) / self.feat_std).max(axis=1)
        span = max(self.z_threshold - self.z_median, 1e-6)
        return np.clip(50.0 + 50.0 * (self.z_threshold - max_z) / span, 0.0, 100.0)

    def health(self, X: np.ndarray) -> np.ndarray:
        return (self.health_forest(X) + self.health_zscore(X)) / 2.0

    def contributors(self, x: np.ndarray, top: int = 5) -> list[dict]:
        """Explain one window: features furthest from their commissioning baseline (z-score)."""
        z = (x - self.feat_mean) / self.feat_std
        order = np.argsort(-np.abs(z))[:top]
        out = []
        for i in order:
            name = self.features[i]
            out.append({
                "feature": name,
                "sensor": sensor_of(name),
                "z": round(float(z[i]), 2),
                "direction": "above" if z[i] > 0 else "below",
                "value": round(float(x[i]), 3),
                "baseline": round(float(self.feat_mean[i]), 3),
            })
        return out

    def control_limits(self) -> list[dict]:
        """X-bar style limits (mean +/- 3 sigma) for each window feature."""
        return [
            {"feature": f, "lcl": float(m - 3 * s), "center": float(m), "ucl": float(m + 3 * s)}
            for f, m, s in zip(self.features, self.feat_mean, self.feat_std)
        ]

    def save(self, path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path) -> "HealthModel":
        return joblib.load(path)
