"""Model-vs-observation comparison utilities (used by the Validation tab)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def align(obs: pd.Series, mod: pd.Series, freq: str = "1h") -> pd.DataFrame:
    """Resample both series to a common time step and keep overlapping times."""
    o = obs.resample(freq).mean().rename("obs")
    m = mod.resample(freq).mean().rename("model")
    return pd.concat([o, m], axis=1).dropna()


def metrics(df: pd.DataFrame) -> dict:
    """Standard skill metrics on an aligned frame with columns 'obs' and 'model'."""
    if df.empty:
        return {}
    o, m = df["obs"].to_numpy(), df["model"].to_numpy()
    err = m - o
    rmse = float(np.sqrt(np.mean(err ** 2)))
    return {
        "N": int(len(o)),
        "Bias": float(np.mean(err)),
        "RMSE": rmse,
        "MAE": float(np.mean(np.abs(err))),
        "R": float(np.corrcoef(o, m)[0, 1]) if len(o) > 1 else np.nan,
        "Scatter index": rmse / float(np.mean(np.abs(o))) if np.mean(np.abs(o)) else np.nan,
        # Willmott (1981) index of agreement
        "Willmott d": float(1 - np.sum(err ** 2) /
                            np.sum((np.abs(m - o.mean()) + np.abs(o - o.mean())) ** 2)),
    }
