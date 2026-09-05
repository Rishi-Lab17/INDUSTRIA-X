"""Stage 6 analysis agents. They extend — never duplicate — the Stage 5
agent architecture: deterministic local analysis producing structured,
auditable evidence (no LLM calls here; interpretation happens downstream
only when a model is actually available).
"""
from ..db import connect as app_connect
from ..multimodal import sensor_analysis as A


class DataAnalysisAgent:
    """Sensor/time-series analysis agent."""

    name = "DataAnalysisAgent"

    def analyze(self, *, rows: list, channel: str, method: str = "rolling_zscore",
                window: int = 60, threshold: float = 3.0,
                gt: float | None = None, lt: float | None = None,
                event_window: dict | None = None,
                compare_channel: str | None = None) -> dict:
        tss, vals = A.series_for(rows, channel)
        if len(vals) < 5:
            return {"agent": self.name, "channel": channel,
                    "status": "INSUFFICIENT_DATA",
                    "observation": "Fewer than 5 valid samples.",
                    "statistics": {"n": len(vals)}}
        stats = A.statistics(tss, vals)
        roll = A.rolling(tss, vals, window)
        trend = A.trend(tss, vals)
        anom = A.anomalies(tss, vals, method=method, window=window,
                           threshold=threshold, gt=gt, lt=lt)
        out: dict = {"agent": self.name, "channel": channel,
                     "method": method, "window": window, "threshold": threshold,
                     "statistics": stats, "trend": trend, "anomalies": anom,
                     "n": len(vals)}
        if compare_channel and compare_channel != channel:
            t2, v2 = A.series_for(rows, compare_channel)
            # pairwise-complete alignment on shared timestamps
            m1 = {t: v for t, v in zip(tss.tolist(), vals.tolist())}
            m2 = {t: v for t, v in zip(t2.tolist(), v2.tolist())}
            common = sorted(set(m1) & set(m2))
            import numpy as np
            corr = A.pearson(np.array([m1[t] for t in common]),
                             np.array([m2[t] for t in common]))
            out["correlation"] = {"channel": compare_channel, **corr}
        if event_window:
            out["event"] = self.event_slice(rows, channel, event_window, anom)
        return out

    def event_slice(self, rows: list, channel: str, window: dict,
                    anomalies: dict) -> dict:
        start, end = float(window["start"]), float(window["end"])
        if end <= start:
            raise ValueError("Event window end must be after start")
        span = end - start
        tss, vals = A.series_for(rows, channel)
        ev_m = (tss >= start) & (tss <= end)
        pre_m = (tss >= start - span) & (tss < start)
        post_m = (tss > end) & (tss <= end + span)
        ev_anom = [e for e in anomalies.get("events", [])
                   if start <= e["ts"] <= end]
        base = A.statistics(tss[pre_m], vals[pre_m]) if pre_m.any() else None
        return {"window": {"start": start, "end": end},
                "baseline_before": base,
                "event_stats": A.statistics(tss[ev_m], vals[ev_m]) if ev_m.any()
                else {"n": 0},
                "after_stats": A.statistics(tss[post_m], vals[post_m]) if post_m.any()
                else {"n": 0},
                "anomalies_in_window": len(ev_anom),
                "observation": f"{len(ev_anom)} anomalie(s) inside the selected window."}


class VisionAgent:
    """Image intelligence agent: quality + metadata + local OCR + regions."""

    name = "VisionAgent"

    def analyze(self, *, image_path, original_filename: str,
                ocr_text: str | None, ocr_status: str,
                quality: dict, annotations: list) -> dict:
        regions = [{"label": a["label"], "note": a.get("note", ""),
                    "bbox": [a["x"], a["y"], a["w"], a["h"]]}
                   for a in annotations]
        findings = []
        if quality.get("status") == "POOR":
            findings.append("Image quality is POOR: "
                            + "; ".join(quality.get("reasons", [])))
        for r in regions:
            findings.append(
                f"Potential visual indication labeled '{r['label']}'"
                + (f": {r['note']}" if r["note"] else "")
                + " (user-marked region, not an automated diagnosis).")
        return {"agent": self.name,
                "quality": quality.get("status"),
                "quality_reasons": quality.get("reasons", []),
                "ocr_status": ocr_status,
                "ocr_text": ocr_text or "",
                "regions": regions,
                "findings": findings,
                "limitation": "Regions are human-marked observations. No automated "
                              "defect diagnosis was performed."}


def load_dataset_rows(dataset_id: int) -> tuple[dict, list]:
    """Returns (dataset_row, rows[(ts, {channel: value})])."""
    con = app_connect()
    try:
        ds = con.execute("SELECT * FROM sensor_datasets WHERE id = ?",
                         (dataset_id,)).fetchone()
        if ds is None:
            raise LookupError("Dataset not found")
        pts = con.execute("SELECT ts, channel, value FROM sensor_readings"
                          " WHERE dataset_id = ? ORDER BY ts",
                          (dataset_id,)).fetchall()
    finally:
        con.close()
    merged: dict[float, dict] = {}
    for ts, ch, v in pts:
        merged.setdefault(float(ts), {})[ch] = float(v)
    return dict(ds), [(t, merged[t]) for t in sorted(merged)]
