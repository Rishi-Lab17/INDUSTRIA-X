"""Sensor data-quality engine. Heuristic score (0-100, documented below) plus
an explicit GOOD/WARNING/POOR/INVALID status. The score is a data-quality
heuristic, NOT a calibrated probability.
"""
import numpy as np


def assess(ingest: dict, channel: str) -> dict:
    vals = np.array([r[1].get(channel) for r in ingest["rows"]], dtype=float)
    valid = vals[~np.isnan(vals)]
    n = len(vals)
    issues: list[str] = []
    score = 100.0

    def hit(points: float, msg: str):
        nonlocal score
        score -= points
        issues.append(msg)

    if n < 10:
        return {"status": "INVALID", "score": 0.0, "issues": ["insufficient sample count (<10)"],
                **_counts(ingest, n, len(valid))}
    if ingest["time_end"] - ingest["time_start"] <= 0:
        return {"status": "INVALID", "score": 0.0, "issues": ["insufficient time span"],
                **_counts(ingest, n, len(valid))}
    if ingest["duplicate_timestamps"]:
        hit(10, f"{ingest['duplicate_timestamps']} duplicate timestamps")
    if ingest["non_monotonic"]:
        hit(15, f"{ingest['non_monotonic']} out-of-order timestamps")
    if ingest["irregular_sampling"]:
        hit(10, "irregular sampling intervals")
    if ingest["gap_count"]:
        hit(min(20, 5 * ingest["gap_count"]), f"{ingest['gap_count']} sampling gaps")
    miss_rate = (n - len(valid)) / n
    if miss_rate > 0:
        hit(min(25, round(100 * miss_rate)),
            f"{n - len(valid)} missing values ({miss_rate:.1%})")
    if len(valid) >= 3:
        if float(np.all(valid == valid[0])):
            hit(20, "constant signal (no variation)")
        q1, q3 = np.percentile(valid, [25, 75])
        iqr = q3 - q1
        if iqr > 0:
            extreme = valid[(valid < q1 - 5 * iqr) | (valid > q3 + 5 * iqr)]
            if len(extreme):
                hit(min(15, 3 * len(extreme)),
                    f"{len(extreme)} extreme outliers (>5x IQR)")
    if len(valid) == 0:
        return {"status": "INVALID", "score": 0.0, "issues": ["no valid values"],
                **_counts(ingest, n, 0)}
    score = max(0.0, round(score, 1))
    status = "GOOD" if score >= 80 else ("WARNING" if score >= 50 else "POOR")
    return {"status": status, "score": score, "issues": issues,
            **_counts(ingest, n, len(valid))}


def _counts(ingest: dict, n: int, n_valid: int) -> dict:
    span = ingest["time_end"] - ingest["time_start"] if ingest["time_end"] else 0
    return {
        "rows": n,
        "valid_rows": n_valid,
        "invalid_rows": n - n_valid + ingest["invalid_numeric"],
        "missing_values": ingest["missing_values"],
        "sampling_interval_s": ingest["median_interval_s"],
        "time_start": ingest["time_start"],
        "time_end": ingest["time_end"],
        "time_span_s": span,
    }
