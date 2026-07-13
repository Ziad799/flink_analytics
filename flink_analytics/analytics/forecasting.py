"""Time-series forecasting: Holt / Holt-Winters exponential smoothing with
automatic frequency + seasonality detection and a linear-trend fallback.
Pure numpy - no heavy dependencies."""
import numpy as np
import pandas as pd
from .profiler import coerce_datetime, to_native

_SEASON_BY_FREQ = {"D": 7, "W": 52, "M": 12, "MS": 12, "Q": 4, "QS": 4, "H": 24, "h": 24}


def _infer_freq(idx: pd.DatetimeIndex) -> str:
    freq = pd.infer_freq(idx)
    if freq:
        return freq
    if len(idx) < 3:
        return "D"
    delta = np.median(np.diff(idx.values).astype("timedelta64[h]").astype(float))
    if delta <= 1.5:
        return "h"
    if delta <= 36:
        return "D"
    if delta <= 24 * 10:
        return "W"
    if delta <= 24 * 45:
        return "MS"
    return "QS"


def _holt_winters(y: np.ndarray, season_len: int | None, alpha=0.35, beta=0.12, gamma=0.25):
    """Additive Holt(-Winters). Returns fitted values and (level, trend, seasonals)."""
    n = len(y)
    use_season = season_len is not None and n >= 2 * season_len
    if use_season:
        seasonals = np.zeros(season_len)
        cycles = n // season_len
        cycle_means = [y[i * season_len:(i + 1) * season_len].mean() for i in range(cycles)]
        for i in range(season_len):
            seasonals[i] = np.mean(
                [y[c * season_len + i] - cycle_means[c] for c in range(cycles)]
            )
    else:
        seasonals = None

    level = y[0]
    trend = (y[min(n - 1, max(1, season_len or 2))] - y[0]) / max(1, (season_len or 2))
    fitted = np.zeros(n)
    for t in range(n):
        s = seasonals[t % season_len] if use_season else 0.0
        fitted[t] = level + trend + s
        last_level = level
        level = alpha * (y[t] - s) + (1 - alpha) * (level + trend)
        trend = beta * (level - last_level) + (1 - beta) * trend
        if use_season:
            seasonals[t % season_len] = gamma * (y[t] - level) + (1 - gamma) * seasonals[t % season_len]
    return fitted, (level, trend, seasonals if use_season else None, season_len, n)


def _hw_forecast(state, periods: int) -> np.ndarray:
    level, trend, seasonals, season_len, n = state
    out = np.zeros(periods)
    for h in range(1, periods + 1):
        s = seasonals[(n + h - 1) % season_len] if seasonals is not None else 0.0
        out[h - 1] = level + h * trend + s
    return out


def forecast_series(
    df: pd.DataFrame, date_col: str, value_col: str, periods: int = 12, freq: str | None = None
) -> dict:
    if date_col not in df.columns or value_col not in df.columns:
        raise ValueError("date_column or value_column not found in dataset")

    dates = coerce_datetime(df[date_col])
    values = pd.to_numeric(df[value_col], errors="coerce")
    ts = pd.DataFrame({"date": dates, "value": values}).dropna()
    if len(ts) < 6:
        raise ValueError("Need at least 6 valid (date, value) pairs to forecast")

    ts = ts.groupby("date", as_index=True)["value"].sum().sort_index()
    freq = freq or _infer_freq(ts.index)
    resampled = ts.resample(freq).sum()
    # Fill short gaps by interpolation
    resampled = resampled.interpolate(limit=3).dropna()
    if len(resampled) < 6:
        raise ValueError("Not enough periods after resampling - try a coarser frequency")

    y = resampled.values.astype(float)
    season_len = _SEASON_BY_FREQ.get(freq[:2].rstrip("-"), _SEASON_BY_FREQ.get(freq[0], None))
    if season_len and len(y) < 2 * season_len:
        season_len = None

    method = "holt_winters" if season_len else "holt_linear"
    try:
        fitted, state = _holt_winters(y, season_len)
        preds = _hw_forecast(state, periods)
        residuals = y - fitted
    except Exception:
        # Linear regression fallback
        method = "linear_trend"
        x = np.arange(len(y))
        coef = np.polyfit(x, y, 1)
        fitted = np.polyval(coef, x)
        preds = np.polyval(coef, np.arange(len(y), len(y) + periods))
        residuals = y - fitted

    resid_std = float(np.std(residuals)) if len(residuals) > 1 else 0.0
    band = 1.96 * resid_std * np.sqrt(np.arange(1, periods + 1) / max(1, periods) + 1)

    future_idx = pd.date_range(resampled.index[-1], periods=periods + 1, freq=freq)[1:]

    denom = np.abs(y).mean() or 1.0
    mape_like = float(np.mean(np.abs(residuals)) / denom * 100)

    slope = (preds[-1] - y[-1]) / max(1, periods)
    direction = "increasing" if slope > 0.01 * denom / 100 else ("decreasing" if slope < -0.01 * denom / 100 else "stable")

    return to_native({
        "method": method,
        "freq": freq,
        "seasonality": season_len,
        "in_sample_error_pct": round(mape_like, 2),
        "trend_direction": direction,
        "history": {
            "dates": [d.isoformat() for d in resampled.index],
            "values": y.tolist(),
        },
        "forecast": {
            "dates": [d.isoformat() for d in future_idx],
            "values": preds.tolist(),
            "lower": (preds - band).tolist(),
            "upper": (preds + band).tolist(),
        },
    })
