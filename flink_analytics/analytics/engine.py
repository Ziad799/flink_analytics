"""Automated full analysis: profiling, correlations, trends over time,
categorical breakdowns, anomaly detection, clustering, and plain-language
statistical findings (no AI required)."""
import numpy as np
import pandas as pd
try:
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:  # segmentation + multivariate anomalies degrade gracefully
    HAS_SKLEARN = False

from .profiler import coerce_datetime, detect_semantic_type, profile_dataframe, to_native

MAX_ANALYSIS_ROWS = 100_000


def _column_types(df: pd.DataFrame) -> dict[str, str]:
    return {c: detect_semantic_type(df[c], c) for c in df.columns}


def _correlations(df: pd.DataFrame, numeric_cols: list[str]) -> dict:
    if len(numeric_cols) < 2:
        return {"pairs": [], "matrix": None}
    num = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    corr = num.corr(method="pearson")
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr.iloc[i, j]
            if pd.notna(v) and abs(v) >= 0.3:
                pairs.append({
                    "a": cols[i], "b": cols[j], "r": round(float(v), 3),
                    "strength": "strong" if abs(v) >= 0.7 else "moderate",
                    "direction": "positive" if v > 0 else "negative",
                })
    pairs.sort(key=lambda p: -abs(p["r"]))
    matrix = {
        "columns": cols,
        "values": [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in corr.values],
    }
    return {"pairs": pairs[:20], "matrix": matrix}


def _time_trends(df: pd.DataFrame, types: dict[str, str], numeric_cols: list[str]) -> list[dict]:
    date_cols = [c for c, t in types.items() if t == "datetime"]
    trends = []
    for dcol in date_cols[:2]:
        dt = coerce_datetime(df[dcol])
        if dt.notna().sum() < 5:
            continue
        span_days = (dt.max() - dt.min()).days or 1
        freq = "MS" if span_days > 120 else ("W" if span_days > 21 else "D")
        for vcol in numeric_cols[:4]:
            series = pd.DataFrame({
                "d": dt, "v": pd.to_numeric(df[vcol], errors="coerce")
            }).dropna()
            if len(series) < 5:
                continue
            agg = series.set_index("d")["v"].resample(freq).sum().dropna()
            if len(agg) < 3:
                continue
            x = np.arange(len(agg))
            slope = np.polyfit(x, agg.values, 1)[0]
            mean_v = np.abs(agg.values).mean() or 1
            pct_per_period = slope / mean_v * 100
            trends.append({
                "date_column": dcol,
                "value_column": vcol,
                "freq": freq,
                "dates": [d.isoformat() for d in agg.index],
                "values": [round(float(v), 4) for v in agg.values],
                "trend_pct_per_period": round(float(pct_per_period), 2),
                "direction": "up" if pct_per_period > 1 else ("down" if pct_per_period < -1 else "flat"),
            })
    return trends


def _categorical_breakdowns(df: pd.DataFrame, types: dict[str, str], numeric_cols: list[str]) -> list[dict]:
    cat_cols = [c for c, t in types.items() if t == "categorical"][:4]
    out = []
    for ccol in cat_cols:
        counts = df[ccol].astype(str).value_counts().head(12)
        item = {
            "column": ccol,
            "categories": [str(k)[:60] for k in counts.index],
            "counts": counts.astype(int).tolist(),
        }
        # aggregate the first numeric column per category, if any
        if numeric_cols:
            vcol = numeric_cols[0]
            agg = (
                df.assign(_v=pd.to_numeric(df[vcol], errors="coerce"))
                .groupby(df[ccol].astype(str))["_v"].sum()
                .reindex(counts.index)
            )
            item["value_column"] = vcol
            item["value_sums"] = [None if pd.isna(v) else round(float(v), 4) for v in agg.values]
        out.append(item)
    return out


def _anomalies(df: pd.DataFrame, numeric_cols: list[str]) -> dict:
    result = {"by_column": [], "multivariate": None}
    # Univariate: IQR method
    for col in numeric_cols[:8]:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) < 20 or s.nunique() < 5:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = s[(s < lo) | (s > hi)]
        if len(outliers) == 0:
            continue
        result["by_column"].append({
            "column": col,
            "count": int(len(outliers)),
            "pct": round(len(outliers) / len(s) * 100, 2),
            "lower_bound": round(float(lo), 4),
            "upper_bound": round(float(hi), 4),
            "examples": [round(float(v), 4) for v in outliers.head(5)],
        })
    if not HAS_SKLEARN:
        return result
    # Multivariate: IsolationForest
    usable = [c for c in numeric_cols if pd.to_numeric(df[c], errors="coerce").notna().sum() > 50]
    if len(usable) >= 2 and len(df) >= 100:
        X = df[usable].apply(pd.to_numeric, errors="coerce").dropna()
        if len(X) >= 100:
            iso = IsolationForest(contamination=0.02, random_state=42, n_estimators=100)
            labels = iso.fit_predict(StandardScaler().fit_transform(X))
            n_anom = int((labels == -1).sum())
            idx = X.index[labels == -1][:10]
            result["multivariate"] = {
                "columns": usable,
                "count": n_anom,
                "pct": round(n_anom / len(X) * 100, 2),
                "sample_row_indices": [int(i) for i in idx],
            }
    return result


def _segments(df: pd.DataFrame, numeric_cols: list[str]) -> dict | None:
    if not HAS_SKLEARN:
        return None
    usable = [c for c in numeric_cols if pd.to_numeric(df[c], errors="coerce").notna().sum() > 50]
    if len(usable) < 2 or len(df) < 100:
        return None
    X = df[usable].apply(pd.to_numeric, errors="coerce").dropna()
    if len(X) < 100:
        return None
    Xs = StandardScaler().fit_transform(X)
    best_k, best_inertia_drop = 3, 0
    inertias = {}
    for k in (2, 3, 4, 5):
        km = KMeans(n_clusters=k, n_init=5, random_state=42).fit(Xs)
        inertias[k] = km.inertia_
    for k in (3, 4, 5):
        drop = (inertias[k - 1] - inertias[k]) / inertias[k - 1]
        if drop > best_inertia_drop:
            best_inertia_drop, best_k = drop, k
    km = KMeans(n_clusters=best_k, n_init=10, random_state=42).fit(Xs)
    X_ = X.copy()
    X_["_cluster"] = km.labels_
    profiles = []
    overall_means = X.mean()
    for c in range(best_k):
        sub = X_[X_["_cluster"] == c]
        traits = []
        for col in usable:
            diff_pct = (sub[col].mean() - overall_means[col]) / (abs(overall_means[col]) or 1) * 100
            if abs(diff_pct) > 15:
                traits.append(f"{col} {'+' if diff_pct > 0 else ''}{diff_pct:.0f}% vs average")
        profiles.append({
            "segment": c,
            "size": int(len(sub)),
            "pct": round(len(sub) / len(X_) * 100, 1),
            "means": {col: round(float(sub[col].mean()), 4) for col in usable},
            "distinctive_traits": traits[:4],
        })
    return {"k": best_k, "columns": usable, "profiles": profiles}


def _key_findings(profile: dict, corr: dict, trends: list, anomalies: dict, segments) -> list[str]:
    findings = []
    qs = profile["quality_score"]
    findings.append(
        f"Dataset has {profile['rows']:,} rows x {profile['cols']} columns "
        f"with a data-quality score of {qs}/100."
    )
    for w in profile["warnings"][:3]:
        findings.append(f"Data quality: {w}.")
    for p in corr["pairs"][:3]:
        findings.append(
            f"{p['strength'].capitalize()} {p['direction']} relationship between "
            f"'{p['a']}' and '{p['b']}' (r={p['r']})."
        )
    for t in trends[:3]:
        if t["direction"] != "flat":
            findings.append(
                f"'{t['value_column']}' is trending {t['direction']} "
                f"~{abs(t['trend_pct_per_period'])}% per period over '{t['date_column']}'."
            )
    for a in anomalies["by_column"][:2]:
        findings.append(
            f"'{a['column']}' contains {a['count']} outliers ({a['pct']}% of values) "
            f"outside [{a['lower_bound']}, {a['upper_bound']}]."
        )
    if anomalies.get("multivariate"):
        m = anomalies["multivariate"]
        findings.append(
            f"Multivariate anomaly scan flagged {m['count']} unusual records ({m['pct']}%)."
        )
    if segments:
        findings.append(
            f"Records naturally group into {segments['k']} segments; "
            f"largest covers {max(p['pct'] for p in segments['profiles'])}% of data."
        )
    return findings


def run_full_analysis(df: pd.DataFrame) -> dict:
    if len(df) > MAX_ANALYSIS_ROWS:
        df = df.sample(MAX_ANALYSIS_ROWS, random_state=42).reset_index(drop=True)

    types = _column_types(df)
    numeric_cols = [c for c, t in types.items() if t == "numeric"]

    profile = profile_dataframe(df)
    corr = _correlations(df, numeric_cols)
    trends = _time_trends(df, types, numeric_cols)
    cats = _categorical_breakdowns(df, types, numeric_cols)
    anomalies = _anomalies(df, numeric_cols)
    segments = _segments(df, numeric_cols)
    findings = _key_findings(profile, corr, trends, anomalies, segments)

    return to_native({
        "profile": profile,
        "correlations": corr,
        "time_trends": trends,
        "categorical_breakdowns": cats,
        "anomalies": anomalies,
        "segments": segments,
        "key_findings": findings,
        "forecastable": [
            {"date_column": t["date_column"], "value_column": t["value_column"]}
            for t in trends
        ],
    })
