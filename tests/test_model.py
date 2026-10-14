import numpy as np
import pandas as pd

from common.alarm import AlarmTracker
from common.features import ANALOG, feature_names, sliding_features, window_features
from common.health import HealthModel


def test_streaming_and_batch_features_match():
    """Training (batch) and live (streaming) must compute identical features."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(5, 1, size=(400, len(ANALOG))), columns=ANALOG)
    df["timestamp"] = pd.date_range("2020-01-01", periods=400, freq="10s")
    batch, _ = sliding_features(df, 180, 10)
    live = window_features(df[ANALOG].to_numpy(dtype=np.float32)[10:190])
    np.testing.assert_allclose(batch.iloc[1].to_numpy(), live, rtol=1e-5)
    assert list(batch.columns) == feature_names()


def test_health_drops_for_abnormal_windows():
    rng = np.random.default_rng(1)
    X = rng.normal(0, 1, size=(3000, len(feature_names())))
    model = HealthModel.fit(X)
    normal = model.health(rng.normal(0, 1, size=(200, X.shape[1])))
    abnormal = model.health(rng.normal(8, 1, size=(20, X.shape[1])))
    assert np.median(normal) > 70
    assert abnormal.max() < 50


def test_alarm_needs_persistence_and_hysteresis():
    t = AlarmTracker(open_after=3, close_after=2)
    assert [t.update(h) for h in (40, 40, 80, 40, 40, 40)] == [None, None, None, None, None, "open"]
    assert t.update(60) is None          # between thresholds: no change
    assert [t.update(h) for h in (90, 90)] == [None, "close"]
