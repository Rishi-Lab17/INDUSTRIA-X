# Stage 6 — Sensor Intelligence + Vision Intelligence + Multimodal Investigation

Stage 6 fuses sensor data, inspection images, equipment, documents, and Stage 4
RAG into evidence-grounded investigation contexts. All math is local
(numpy + PIL). No external AI/vision/OCR calls. No Kimi dependency:
deterministic analysis always works; AI interpretation attaches only when a
model runtime is actually available.

## Architecture

```
CSV → sensor_ingest (multi-format parse, quality counters, caps)
   → storage/sensor_data/{company}/{id}/original.csv + sensor_readings rows
   → quality engine → statistics/trend/anomaly/FFT/correlation/event/export
Images → vision_ingest (validate, metadata, quality) → storage/images/...
   → local OCR (tesseract if present) → regions/annotations
Both → analysis_runs provenance rows + audit events
Multimodal → fusion (typed evidence, O/I/L observations, timeline, snapshots)
   → optional Stage 5 orchestrator interpretation (model-gated)
```

Modules: `backend/app/multimodal/` (sensor_ingest, sensor_quality,
sensor_analysis, vision_ingest, fusion), `backend/app/agents/analysis_agents.py`
(DataAnalysisAgent, VisionAgent), routers `sensors.py`, `vision.py`,
`investigations.py`. Stage 5 `agents/tools.py` gains `analyze_sensor_data` and
`analyze_vision_image` (ADMIN + ENGINEER).

## Sensor pipeline

Accepted: `timestamp,value`, `timestamp,sensor_name,value` (long),
`timestamp,ch1,ch2,...` (wide). Header required; timestamps accept ISO-8601,
common formats, and epoch s/ms/us (range-checked 2000–2100). Units parsed
from `name [unit]` headers. Every skipped row is counted with samples kept
(max 25 messages). Caps: `SENSOR_MAX_ROWS=100000`, `SENSOR_MAX_CHANNELS=32`,
file cap `MAX_UPLOAD_SIZE_MB`.

Readings stored long-format: `(dataset_id, ts, channel, value)` indexed.
Raw bytes preserved; stored invalid rows are excluded from analysis.

## Data quality

Status GOOD (≥80) / WARNING (≥50) / POOR / INVALID with an explicit heuristic
score (documented as NOT a calibrated probability): −10 duplicates, −15
out-of-order, −10 irregular, −5/gap (≤20), missing-rate scaled (≤25), −20
constant signal, outliers ≤15, 0 on <10 samples/empty span/no values.
Stored at upload (`quality_detail` JSON); the quality endpoint returns the
stored assessment plus live row counts.

## Calculations (formulas documented in `sensor_analysis.py`)

min/max/mean/median/std(var, population)/variance/percentiles/RMS/peak/
peak-to-peak/CV (null when mean=0)/crest factor/rate of change/rolling
mean+std. Trend: least-squares slope; STABLE when fitted change across span
< 10% of std; baseline = first 20% mean, recent = last 20% mean.
Anomalies: z-score, rolling z-score, IQR (1.5 fences), absolute gt/lt
thresholds (missing thresholds → "No configured engineering threshold.").
Language is fixed to "Statistical anomaly detected."
FFT: mean-detrended rFFT; requires n ≥ 64 and uniform sampling; gaps ≤5%
are linearly interpolated and REPORTED (`interpolated_points` + warning);
larger gaps → "Frequency analysis unavailable for this dataset." Peaks are
top-5 local maxima excl. DC. Pearson r on pairwise-complete samples (n≥10),
worded "Correlation observed, not causation."
Event windows: equal-length pre-window baseline, in-window stats, post stats,
anomaly count. Charts: server-side stride downsampling (flagged) preserving
anomaly markers; export returns full-fidelity CSV.

## Vision pipeline

JPG/JPEG/PNG/WEBP; extension + magic + declared-MIME cross-check; corrupt →
422; oversized images downscaled for storage (original dimensions recorded).
Quality heuristics (documented, uncalibrated): resolution floors, Laplacian
blur metric, brightness extremes → GOOD/WARNING/POOR + reasons. POOR refuses
reasoning with the reason. OCR via Stage 3 local Tesseract abstraction:
COMPLETED / FAILED / UNAVAILABLE (honest; this machine has no tesseract
binary). Regions: normalized 0–1 boxes, fixed label set, notes; create any
role, edit/delete author-or-admin; persisted per company/asset.

## Multimodal

`POST /api/investigations/multimodal` (ADMIN/ENGINEER): validates all
references belong to the same company AND equipment; runs RAG (Stage 4,
equipment-scoped) + sensor summaries + image findings; `fusion.correlate`
emits only OBSERVATION/INTERPRETATION/LIMITATION items with safety language
("may indicate", "requires engineering verification", never diagnoses or
prescribes); timeline sorted (nulls last); warnings aggregated; optional
`ai_session_id` → Stage 5 interpretation ONLY if a model is ONLINE, else
`MODEL UNAVAILABLE` limitation. Snapshots store config+results JSON
(reproducible) with list/get. Every run writes `analysis_runs` provenance
(method/params/result/warnings) + audit events.

## Evidence model

Types: DOCUMENT, SENSOR, IMAGE, OCR, CALCULATION, USER_INPUT,
SYSTEM_OBSERVATION. Each: id, type, source, timestamp?, equipment,
description, data_ref.

## Configuration (.env)

`SENSOR_MAX_ROWS`, `SENSOR_MAX_CHANNELS`, `CHART_MAX_POINTS=2000`,
`FFT_MIN_SAMPLES=64`, `IMAGE_MAX_DIMENSION=4096`,
`ANOMALY_DEFAULT_{METHOD,WINDOW,THRESHOLD}`. No keys required.

## Testing

`tests/test_stage6_multimodal.py` (23 tests): ingest shapes/units, malformed/
missing/duplicate/irregular/oversize, exact statistics, trend directions,
all anomaly methods + safety language, threshold-without-config note, FFT
valid/irregular, correlation + event windows, chart downsampling + export,
image validation/metadata/quality states, honest OCR, POOR refusal, annotation
CRUD + authz + validation, multimodal evidence/tags/timeline/snapshot,
scoping/validation errors, cross-company 404s, RBAC matrix, audit + provenance
rows, agent tool execution scoping.

## Demo data (`data/demo/`, synthetic, tracked)

`sensors/p204_{vibration,temperature,rpm}.csv` (12k 1 Hz rows; vibration has a
controlled 14:20–14:45 abnormal event + 2 honest gaps), `images/p204_inspection.png`
(synthetic sketch). Generated by an inline script; values are fictional.

## Performance (measured, RTX 3050 laptop / Ryzen 5)

- 12k-row CSV upload + parse + quality: ~0.5 s
- Rolling-zscore analysis over 12k rows: ~1.3 s
- Full pytest suite (105 tests): ~3 min (bcrypt cost dominates)

## Limitations

- No tesseract binary → image/scanned OCR unavailable (honest state).
- Synchronous in-request analysis (prototype scale; queue is Stage 10).
- CSV only for sensors (Stage 3 document CSVs are separate concerns).
- Charts are SVG line charts (no 3D/spectrogram rendering).
- Equipment QR payloads still relative paths (Stage 9/10).
- Absolute physical safety interlocks are out of scope (Stage 8).
