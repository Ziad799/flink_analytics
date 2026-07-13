"""Automated dataset profiling: semantic type detection, per-column stats,
histograms, data-quality scoring and warnings."""
import numpy as np
import pandas as pd


def to_native(obj):
    """Recursively convert numpy/pandas types to JSON-safe python natives."""
    if isinstance(obj, dict):
        return {str(k): to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else round(obj, 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(obj).isoformat()
    if obj is pd.NaT:
        return None
    return obj


def detect_semantic_type(series: pd.Series, col_name: str = "") -> str:
    """Classify a column: numeric | datetime | boolean | categorical | text | id."""
    s = series.dropna()
    if s.empty:
        return "empty"
    n = len(s)

    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        nunique = s.nunique()
        if nunique <= 2 and set(pd.unique(s)).issubset({0, 1}):
            return "boolean"
        # integer column where every value is unique -> likely an ID
        if nunique == n and pd.api.types.is_integer_dtype(series) and n > 20:
            return "id"
        return "numeric"

    # object columns: try datetime, then boolean-ish, then categorical vs text
    sample = s.astype(str).head(500)
    try:
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        if parsed.notna().mean() > 0.9:
            return "datetime"
    except Exception:
        pass

    lowered = set(sample.str.lower().unique())
    if lowered.issubset({"true", "false", "yes", "no", "y", "n", "0", "1"}):
        return "boolean"

    nunique = s.nunique()
    if nunique == n and n > 20:
        return "id"
    if nunique <= max(20, n * 0.05):
        return "categorical"
    avg_len = sample.str.len().mean()
    return "text" if avg_len > 40 else "categorical"


def coerce_datetime(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce", format="mixed")


def _histogram(s: pd.Series, bins: int = 12) -> dict:
    clean = s.dropna().astype(float)
    if clean.empty or clean.nunique() == 1:
        return {"bins": [], "counts": []}
    counts, edges = np.histogram(clean, bins=bins)
    labels = [f"{edges[i]:.4g}-{edges[i+1]:.4g}" for i in range(len(counts))]
    return {"bins": labels, "counts": counts.tolist()}


def profile_column(series: pd.Series, sem_type: str) -> dict:
    n = len(series)
    nulls = int(series.isna().sum())
    info: dict = {
        "semantic_type": sem_type,
        "dtype": str(series.dtype),
        "nulls": nulls,
        "null_pct": round(nulls / n * 100, 2) if n else 0,
        "unique": int(series.nunique(dropna=True)),
    }
    s = series.dropna()
    if s.empty:
        return info

    if sem_type == "numeric":
        sf = s.astype(float)
        q1, q3 = sf.quantile(0.25), sf.quantile(0.75)
        info.update({
            "min": sf.min(), "max": sf.max(), "mean": sf.mean(),
            "median": sf.median(), "std": sf.std(),
            "q1": q1, "q3": q3,
            "skew": sf.skew() if len(sf) > 2 else 0,
            "zeros": int((sf == 0).sum()),
            "negatives": int((sf < 0).sum()),
            "histogram": _histogram(sf),
        })
    elif sem_type == "datetime":
        dt = coerce_datetime(s)
        dt = dt.dropna()
        if not dt.empty:
            info.update({
                "min": dt.min().isoformat(),
                "max": dt.max().isoformat(),
                "span_days": int((dt.max() - dt.min()).days),
            })
    elif sem_type in ("categorical", "boolean", "text"):
        vc = s.astype(str).value_counts().head(10)
        info["top_values"] = [
            {"value": str(k)[:80], "count": int(v), "pct": round(v / len(s) * 100, 2)}
            for k, v in vc.items()
        ]
    return info


def profile_dataframe(df: pd.DataFrame) -> dict:
    n_rows, n_cols = df.shape
    columns = {}
    type_counts: dict[str, int] = {}
    for col in df.columns:
        sem = detect_semantic_type(df[col], col)
        columns[col] = profile_column(df[col], sem)
        type_counts[sem] = type_counts.get(sem, 0) + 1

    dup_rows = int(df.duplicated().sum())
    total_cells = n_rows * n_cols or 1
    null_cells = int(df.isna().sum().sum())

    warnings = []
    for col, meta in columns.items():
        if meta["null_pct"] > 50:
            warnings.append(f"Column '{col}' is {meta['null_pct']}% empty")
        if meta["semantic_type"] == "empty":
            warnings.append(f"Column '{col}' has no values at all")
        if meta["semantic_type"] == "numeric" and meta.get("std") == 0:
            warnings.append(f"Column '{col}' is constant (no variance)")
    if dup_rows:
        warnings.append(f"{dup_rows} duplicated rows ({round(dup_rows/n_rows*100,1)}%)")

    # Quality score: penalise nulls, duplicates, empty/constant columns
    score = 100.0
    score -= (null_cells / total_cells) * 40
    score -= (dup_rows / n_rows) * 20 if n_rows else 0
    bad_cols = sum(1 for m in columns.values() if m["semantic_type"] == "empty" or m["null_pct"] > 50)
    score -= (bad_cols / n_cols) * 25 if n_cols else 0
    score = max(0.0, round(score, 1))

    return to_native({
        "rows": n_rows,
        "cols": n_cols,
        "duplicated_rows": dup_rows,
        "null_cells_pct": round(null_cells / total_cells * 100, 2),
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
        "type_counts": type_counts,
        "quality_score": score,
        "warnings": warnings,
        "columns": columns,
    })
