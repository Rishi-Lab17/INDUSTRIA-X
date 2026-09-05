"""Deterministic time-series analysis (numpy only).

Formulas:
- RMS = sqrt(mean(x^2)); peak = max(|x|); peak-to-peak = max-min;
  crest factor = peak / RMS; CV = std / mean (mean != 0 else null).
- Trend: least-squares slope over (t, x); direction STABLE when the fitted
  change across the span is < 10% of std (or n < 10 → INSUFFICIENT_DATA).
- Anomalies: z-score |z|>=thr; rolling z-score over trailing window;
  IQR fences at 1.5*IQR; absolute gt/lt thresholds.
- FFT: mean-detrended rFFT; requires uniform sampling (max dt deviation 20%)
  and n >= FFT_MIN_SAMPLES; peaks = top local maxima excluding DC.
- Pearson r on pairwise-complete overlapping samples (n >= 10).

Language rule: results say "statistical anomaly detected", never that
equipment failed. Thresholds come from configuration or explicit user input;
otherwise responses state "No configured engineering threshold."
"""
import numpy as np


def _arr(vals: list) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in vals], dtype=float)


def series_for(rows: list, channel: str):
    tss = np.array([t for t, _ in rows], dtype=float)
    vals = _arr([r[1].get(channel) for r in rows])
    mask = ~np.isnan(vals)
    return tss[mask], vals[mask]


def statistics(tss: np.ndarray, vals: np.ndarray) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0}
    mean = float(np.mean(vals))
    std = float(np.std(vals))
    rms = float(np.sqrt(np.mean(vals ** 2)))
    peak = float(np.max(np.abs(vals)))
    out = {
        "n": n,
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "mean": mean,
        "median": float(np.median(vals)),
        "std": std,
        "variance": float(np.var(vals)),
        "p5": float(np.percentile(vals, 5)),
        "p25": float(np.percentile(vals, 25)),
        "p75": float(np.percentile(vals, 75)),
        "p95": float(np.percentile(vals, 95)),
        "rms": rms,
        "peak": peak,
        "peak_to_peak": float(np.max(vals) - np.min(vals)),
        "cv": (std / mean) if mean != 0 else None,
        "crest_factor": (peak / rms) if rms > 0 else None,
    }
    if n >= 2 and tss[-1] > tss[0]:
        out["rate_of_change_per_s"] = float(np.mean(np.abs(np.diff(vals)))
                                            / np.mean(np.diff(tss)))
    else:
        out["rate_of_change_per_s"] = None
    return out


def rolling(tss: np.ndarray, vals: np.ndarray, window: int) -> dict:
    window = max(2, min(window, len(vals)))
    idx = np.arange(len(vals))
    means = np.array([np.mean(vals[max(0, i - window + 1):i + 1])
                      for i in idx])
    stds = np.array([np.std(vals[max(0, i - window + 1):i + 1]) for i in idx])
    return {"window": window, "times": tss.tolist(),
            "rolling_mean": [round(float(v), 6) for v in means],
            "rolling_std": [round(float(v), 6) for v in stds]}


def trend(tss: np.ndarray, vals: np.ndarray) -> dict:
    n = len(vals)
    if n < 5:
        return {"direction": "INSUFFICIENT_DATA", "slope_per_s": None,
                "slope_per_hour": None, "recent_vs_baseline_pct": None,
                "note": "Fewer than 5 samples"}
    t0 = tss - tss[0]
    slope, intercept = np.polyfit(t0, vals, 1)
    slope = float(slope)
    span = float(t0[-1] - t0[0]) if t0[-1] > t0[0] else 0.0
    std = float(np.std(vals))
    if span <= 0 or std == 0:
        direction = "STABLE"
    else:
        change = abs(slope) * span
        direction = "STABLE" if change < 0.1 * std else (
            "INCREASING" if slope > 0 else "DECREASING")
    k = max(1, n // 5)
    base, recent = float(np.mean(vals[:k])), float(np.mean(vals[-k:]))
    pct = ((recent - base) / abs(base) * 100.0) if base != 0 else None
    return {"direction": direction, "slope_per_s": slope,
            "slope_per_hour": slope * 3600.0,
            "baseline_mean": base, "recent_mean": recent,
            "recent_vs_baseline_pct": pct}


def anomalies(tss: np.ndarray, vals: np.ndarray, *, method: str,
              window: int = 60, threshold: float = 3.0,
              gt: float | None = None, lt: float | None = None) -> dict:
    n = len(vals)
    if n < 5:
        return {"method": method, "count": 0, "events": [],
                "note": "INSUFFICIENT_DATA: fewer than 5 samples"}
    base_mean, base_std = float(np.mean(vals)), float(np.std(vals))
    if method == "zscore":
        if base_std == 0:
            idx = np.array([], dtype=int)
        else:
            idx = np.where(np.abs((vals - base_mean) / base_std) >= threshold)[0]
        baseline = {"mean": base_mean, "std": base_std}
    elif method == "rolling_zscore":
        w = max(2, min(window, n))
        idx = []
        for i in range(n):
            seg = vals[max(0, i - w + 1):i + 1]
            m, sd = float(np.mean(seg)), float(np.std(seg))
            if sd > 0 and abs((vals[i] - m) / sd) >= threshold:
                idx.append(i)
        idx = np.array(idx, dtype=int)
        baseline = {"window": w}
    elif method == "iqr":
        q1, q3 = np.percentile(vals, [25, 75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        idx = np.where((vals < lo) | (vals > hi))[0]
        baseline = {"q1": float(q1), "q3": float(q3), "iqr": float(iqr),
                    "lower": float(lo), "upper": float(hi)}
    elif method == "threshold":
        if gt is None and lt is None:
            return {"method": method, "count": 0, "events": [],
                    "note": "No configured engineering threshold."}
        mask = np.zeros(n, dtype=bool)
        if gt is not None:
            mask |= vals > gt
        if lt is not None:
            mask |= vals < lt
        idx = np.where(mask)[0]
        baseline = {"gt": gt, "lt": lt}
    else:
        raise ValueError(f"Unknown anomaly method: {method}")
    events = [{"ts": float(tss[i]), "value": float(vals[i])} for i in idx]
    duration = float(tss[idx[-1]] - tss[idx[0]]) if len(idx) > 1 else 0.0
    return {"method": method, "threshold": threshold, "baseline": baseline,
            "count": len(events), "events": events,
            "affected_duration_s": duration,
            "language": "Statistical anomaly detected."}


def fft_analysis(tss: np.ndarray, vals: np.ndarray, *, min_samples: int,
                 max_interp_frac: float = 0.05) -> dict:
    n = len(vals)
    if n < min_samples:
        return {"available": False,
                "reason": "Frequency analysis unavailable for this dataset."}
    dts = np.diff(tss)
    if len(dts) == 0 or np.any(dts <= 0):
        return {"available": False,
                "reason": "Frequency analysis unavailable for this dataset."}
    dt = float(np.median(dts))
    if dt <= 0:
        return {"available": False,
                "reason": "Frequency analysis unavailable for this dataset."}
    interpolated = 0
    if float(np.max(np.abs(dts - dt))) > 0.2 * dt:
        # Small gaps: rebuild a uniform grid by linear interpolation (standard
        # practice, reported honestly). Large gaps: refuse.
        grid = np.arange(tss[0], tss[-1] + dt / 2, dt)
        missing = len(grid) - n
        if missing < 0 or missing / max(len(grid), 1) > max_interp_frac:
            return {"available": False,
                    "reason": "Frequency analysis unavailable for this dataset."}
        vals = np.interp(grid, tss, vals)
        tss = grid
        n = len(vals)
        interpolated = int(missing)
        if n < min_samples:
            return {"available": False,
                    "reason": "Frequency analysis unavailable for this dataset."}
    x = vals - np.mean(vals)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, dt)
    mags = np.abs(spec) / n
    peaks = []
    if len(mags) > 2:
        order = np.argsort(mags[1:])[::-1]
        taken = []
        for j in order:
            i = j + 1
            if all(abs(freqs[i] - f) > (freqs[1] - freqs[0]) * 2 for f in taken):
                taken.append(float(freqs[i]))
                peaks.append({"frequency_hz": round(float(freqs[i]), 4),
                              "amplitude": round(float(mags[i]), 6)})
            if len(peaks) >= 5:
                break
    return {"available": True, "sample_rate_hz": round(1.0 / dt, 4),
            "frequency_resolution_hz": round(float(freqs[1] - freqs[0]), 6) if n > 1 else None,
            "n_samples": n, "peaks": peaks,
            "interpolated_points": interpolated,
            "limitation": "Frequency peaks are evidence requiring engineering "
                          "interpretation and do not by themselves identify a failure mode."
            + (f" {interpolated} missing sample(s) were linearly interpolated;"
               " large gaps would refuse analysis." if interpolated else "")}


def pearson(x: np.ndarray, y: np.ndarray) -> dict:
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 10:
        return {"r": None, "n": n, "note": "INSUFFICIENT_DATA: fewer than 10 paired samples"}
    if float(np.std(x)) == 0 or float(np.std(y)) == 0:
        return {"r": None, "n": n, "note": "Undefined: constant signal"}
    r = float(np.corrcoef(x, y)[0, 1])
    return {"r": round(r, 4), "n": n,
            "note": "Correlation observed, not causation."}


def downsample(tss: np.ndarray, vals: np.ndarray, max_points: int,
               keep_idx: set[int] | None = None) -> dict:
    n = len(vals)
    keep_idx = keep_idx or set()
    if n <= max_points:
        return {"times": tss.tolist(), "values": vals.tolist(),
                "downsampled": False}
    stride = max(1, n // max_points)
    idx = sorted(set(range(0, n, stride)) | {i for i in keep_idx if 0 <= i < n})
    return {"times": [float(tss[i]) for i in idx],
            "values": [float(vals[i]) for i in idx],
            "downsampled": True, "stride": stride, "original_n": n}
