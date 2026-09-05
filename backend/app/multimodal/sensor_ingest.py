"""Sensor CSV ingestion: robust multi-format parser.

Accepted shapes (headers required):
  timestamp,value
  timestamp,sensor_name,value            (long format)
  timestamp,vibration_x,...,temperature  (wide multichannel)

Never silently drops rows: every skipped row is counted and sampled in
`problems`. Hard caps from config (SENSOR_MAX_ROWS / SENSOR_MAX_CHANNELS).
"""
import csv
import io
import re
from datetime import datetime, timezone

_TIMESTAMP_NAMES = ("timestamp", "time", "datetime", "date", "ts", "t")
_UNIT_RE = re.compile(r"^(?P<name>.+?)\s*[\[\(](?P<unit>[^\]\)]+)[\]\)]\s*$")

_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d",
)


class IngestError(Exception):
    pass


def _parse_ts(raw: str) -> float:
    s = raw.strip()
    if not s:
        raise ValueError("empty timestamp")
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        v = float(s)
        if v > 1e14:  # microseconds
            v /= 1e6
        elif v > 1e11:  # milliseconds
            v /= 1e3
        if v < 946684800 or v > 4102444800:  # 2000-01-01 .. 2100-01-01
            raise ValueError("epoch out of range")
        return v
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        dt = None
        for fmt in _TS_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(f"unparseable timestamp {s!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _split_unit(header: str) -> tuple[str, str | None]:
    m = _UNIT_RE.match(header.strip())
    if m:
        return m.group("name").strip(), m.group("unit").strip()
    return header.strip(), None


def parse_csv(content: bytes, *, max_rows: int, max_channels: int) -> dict:
    """Returns normalized ingest result. Raises IngestError on fatal problems."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1252")
        except UnicodeDecodeError as e:
            raise IngestError("CSV is not decodable text") from e
    lines = text.splitlines()
    if not lines or not any(line.strip() for line in lines):
        raise IngestError("CSV is empty")
    sample = "\n".join(lines[:10])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(reader)
    except StopIteration as e:
        raise IngestError("CSV has no header row") from e
    header = [(h or "").strip() for h in header]
    if all(re.fullmatch(r"-?\d+(\.\d+)?", h) for h in header if h):
        raise IngestError("CSV header row is missing (first row looks numeric)")
    if len(header) < 2:
        raise IngestError("CSV needs a timestamp column plus at least one value column")

    # Long format? timestamp,sensor_name,value
    lowered = [h.lower() for h in header]
    long_fmt = (
        len(header) == 3
        and lowered[0] in _TIMESTAMP_NAMES
        and lowered[1] in ("sensor", "sensor_name", "channel", "tag", "name", "signal")
    )
    ts_idx = next((i for i, h in enumerate(lowered) if h in _TIMESTAMP_NAMES), 0)

    channels: dict[str, dict] = {}
    rows: list[tuple[float, dict]] = []
    problems: list[str] = []
    dropped = 0
    invalid_numeric = 0
    missing_values = 0
    seen_ts: set[float] = set()
    dup_ts = 0
    prev_ts: float | None = None
    non_monotonic = 0
    data_rows = 0

    def note(msg: str):
        if len(problems) < 25:
            problems.append(msg)

    for lineno, row in enumerate(reader, start=2):
        if not any((c or "").strip() for c in row):
            continue
        data_rows += 1
        if data_rows > max_rows:
            raise IngestError(
                f"CSV exceeds the {max_rows}-row processing limit; trim the file")
        try:
            ts = _parse_ts(row[ts_idx] if ts_idx < len(row) else "")
        except (ValueError, IndexError):
            dropped += 1
            note(f"line {lineno}: bad timestamp, row skipped")
            continue
        if ts in seen_ts:
            dup_ts += 1
        seen_ts.add(ts)
        if prev_ts is not None and ts < prev_ts:
            non_monotonic += 1
        prev_ts = ts if prev_ts is None else max(prev_ts, ts)
        values: dict[str, float | None] = {}
        if long_fmt:
            cname = (row[1] if len(row) > 1 else "").strip() or "value"
            if cname not in channels:
                if len(channels) >= max_channels:
                    dropped += 1
                    note(f"line {lineno}: too many channels, row skipped")
                    continue
                channels[cname] = {"name": cname, "unit": None}
            raw = row[2] if len(row) > 2 else ""
            if not raw.strip():
                missing_values += 1
                values[cname] = None
            else:
                try:
                    values[cname] = float(raw)
                except ValueError:
                    invalid_numeric += 1
                    dropped += 1
                    note(f"line {lineno}: invalid numeric value, row skipped")
                    continue
        else:
            skip_row = False
            for i, h in enumerate(header):
                if i == ts_idx:
                    continue
                name, unit = _split_unit(h or f"col{i+1}")
                if name not in channels:
                    if len(channels) >= max_channels:
                        dropped += 1
                        note(f"line {lineno}: too many channels, row skipped")
                        skip_row = True
                        break
                    channels[name] = {"name": name, "unit": unit}
                raw = row[i] if i < len(row) else ""
                if not raw.strip():
                    missing_values += 1
                    values[name] = None
                else:
                    try:
                        values[name] = float(raw)
                    except ValueError:
                        invalid_numeric += 1
                        dropped += 1
                        note(f"line {lineno}: invalid numeric value, row skipped")
                        skip_row = True
                        break
            if skip_row:
                continue
        rows.append((ts, values))

    if not rows:
        raise IngestError("CSV has no usable data rows")
    rows.sort(key=lambda r: r[0])
    tss = [t for t, _ in rows]
    dts = [b - a for a, b in zip(tss, tss[1:])] if len(tss) > 1 else []
    positive = sorted(d for d in dts if d > 0)
    median_dt = positive[len(positive) // 2] if positive else None
    gaps = [d for d in dts if median_dt and d > 3 * median_dt] if median_dt else []
    irregular = bool(median_dt) and any(
        abs(d - median_dt) > 0.2 * median_dt for d in positive)
    return {
        "channels": [{"name": c["name"], "unit": c["unit"]} for c in channels.values()],
        "rows": rows,
        "row_count": len(rows),
        "time_start": tss[0],
        "time_end": tss[-1],
        "median_interval_s": median_dt,
        "gap_count": len(gaps),
        "irregular_sampling": irregular,
        "duplicate_timestamps": dup_ts,
        "non_monotonic": non_monotonic,
        "missing_values": missing_values,
        "invalid_numeric": invalid_numeric,
        "dropped_rows": dropped,
        "problems": problems,
    }
