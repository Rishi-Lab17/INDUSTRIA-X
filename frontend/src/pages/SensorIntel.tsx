import { useEffect, useState } from "react";
import { api, authedBlob, type Equipment, type SensorDataset } from "../api";
import { useAuth } from "../auth";
import SensorChart from "../components/SensorChart";

function useRole() {
  const { user } = useAuth();
  return {
    canWrite: user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER",
  };
}

function fmtTs(ts: number | null) {
  if (ts === null || ts === undefined) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export default function SensorIntel() {
  const { canWrite } = useRole();
  const [sets, setSets] = useState<SensorDataset[]>([]);
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<SensorDataset | null>(null);
  const [channel, setChannel] = useState("");
  const [series, setSeries] = useState<{ times: number[]; values: number[]; downsampled: boolean } | null>(null);
  const [quality, setQuality] = useState<Record<string, unknown> | null>(null);
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [freq, setFreq] = useState<Record<string, unknown> | null>(null);
  const [corr, setCorr] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  // upload
  const [file, setFile] = useState<File | null>(null);
  const [upEq, setUpEq] = useState("");
  const [upName, setUpName] = useState("");
  // analysis config
  const [method, setMethod] = useState("rolling_zscore");
  const [window, setWindow] = useState(60);
  const [threshold, setThreshold] = useState(3.0);
  const [gt, setGt] = useState("");
  const [lt, setLt] = useState("");
  const [cmpCh, setCmpCh] = useState("");
  const [evStart, setEvStart] = useState("");
  const [evEnd, setEvEnd] = useState("");

  function loadList() {
    api.sensorList().then((r) => setSets(r.datasets)).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    api.equipmentList().then((r) => setEquipment(r.equipment)).catch(() => undefined);
  }
  useEffect(loadList, []);

  async function select(id: number) {
    setSel(id);
    setErr("");
    setAnalysis(null);
    setFreq(null);
    setCorr(null);
    try {
      const d = await api.sensorGet(id);
      setDetail(d);
      setChannel(d.channels[0]?.name ?? "");
      const q = await api.sensorQuality(id);
      setQuality(q);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Load failed");
    }
  }

  useEffect(() => {
    if (sel === null || !channel) return;
    api.sensorSeries(sel, channel)
      .then((s) => setSeries({ times: s.times, values: s.values, downsampled: s.downsampled }))
      .catch(() => setSeries(null));
  }, [sel, channel]);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !upEq) {
      setErr("Choose a CSV file and equipment.");
      return;
    }
    setErr("");
    setOk("");
    setBusy(true);
    try {
      const d = await api.sensorUpload(file, Number(upEq), upName || undefined);
      setOk(`Uploaded ${d.source_filename}: ${d.row_count} rows, quality ${d.quality_status}.`);
      setFile(null);
      loadList();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function runAnalyze() {
    if (sel === null) return;
    setErr("");
    setBusy(true);
    try {
      const body: Record<string, unknown> = { channel, method, window, threshold };
      if (gt !== "") body.gt = Number(gt);
      if (lt !== "") body.lt = Number(lt);
      if (cmpCh) body.compare_channel = cmpCh;
      if (evStart && evEnd) {
        body.event_start = new Date(evStart).getTime() / 1000;
        body.event_end = new Date(evEnd).getTime() / 1000;
      }
      setAnalysis(await api.sensorAnalyze(sel, body) as Record<string, unknown>);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  async function runFreq() {
    if (sel === null) return;
    setErr("");
    try {
      setFreq(await api.sensorFrequency(sel, { channel }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Frequency analysis failed");
    }
  }

  async function runCorr() {
    if (sel === null || !cmpCh) return;
    setErr("");
    try {
      setCorr(await api.sensorCorrelate({ dataset_id: sel, channel_a: channel, channel_b: cmpCh }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Correlation failed");
    }
  }

  async function doExport() {
    if (sel === null) return;
    try {
      const blob = await authedBlob(`/api/sensors/${sel}/export`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dataset-${sel}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Export failed");
    }
  }

  const stats = (analysis?.statistics ?? null) as Record<string, number | null> | null;
  const anoms = (analysis?.anomalies ?? null) as { count: number; events: { ts: number; value: number }[]; method: string; note?: string } | null;

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Sensor Intelligence</h1>
          <p className="page-sub">Local statistical analysis of industrial sensor data — observations, never diagnoses.</p>
        </div>
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      <div className="grid grid-2" style={{ gridTemplateColumns: "300px 1fr" }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Datasets</h3>
          {canWrite && (
            <form onSubmit={upload} style={{ marginBottom: 14 }}>
              <div className="field">
                <label>CSV FILE</label>
                <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </div>
              <div className="field">
                <label>EQUIPMENT</label>
                <select value={upEq} onChange={(e) => setUpEq(e.target.value)} style={selStyle}>
                  <option value="">Select…</option>
                  {equipment.map((e) => <option key={e.id} value={e.id}>{e.code}</option>)}
                </select>
              </div>
              <div className="field">
                <label>NAME (OPTIONAL)</label>
                <input value={upName} onChange={(e) => setUpName(e.target.value)} />
              </div>
              <button className="btn" disabled={busy || !file}>Upload</button>
            </form>
          )}
          {sets.map((d) => (
            <div key={d.id} onClick={() => select(d.id)}
              style={{ padding: "8px 10px", borderRadius: 8, cursor: "pointer", marginBottom: 6, border: "1px solid var(--border)", background: sel === d.id ? "rgba(0,166,199,.14)" : "transparent" }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>{d.name}</div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{d.equipment_code} · {d.row_count} rows · {d.quality_status}</div>
            </div>
          ))}
          {sets.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>No datasets yet.</div>}
        </div>

        <div>
          {!detail ? (
            <div className="panel">Select a dataset to inspect.</div>
          ) : (
            <>
              <div className="panel" style={{ marginBottom: 16 }}>
                <h3 style={{ marginTop: 0 }}>{detail.name} <span className="badge">{detail.quality_status}</span></h3>
                <div className="kv"><span>EQUIPMENT</span><span>{detail.equipment_code}</span></div>
                <div className="kv"><span>CHANNELS</span><span>{detail.channels.map((c) => c.unit ? `${c.name} [${c.unit}]` : c.name).join(", ")}</span></div>
                <div className="kv"><span>ROWS / SPAN</span><span>{detail.row_count} · {fmtTs(detail.time_start)} → {fmtTs(detail.time_end)}</span></div>
                <div className="kv"><span>QUALITY SCORE</span><span>{detail.quality_score} (heuristic, not a probability)</span></div>
                {quality !== null && Array.isArray((quality as { issues?: unknown }).issues) && (
                  <div style={{ fontSize: 12, color: "var(--warning)", marginTop: 6 }}>
                    Issues: {((quality as { issues: string[] }).issues).join("; ") || "none"}
                  </div>
                )}
                <div className="field" style={{ marginTop: 10 }}>
                  <label>CHANNEL</label>
                  <select value={channel} onChange={(e) => setChannel(e.target.value)} style={selStyle}>
                    {detail.channels.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <button className="btn btn-ghost" onClick={doExport}>Export CSV</button>
              </div>

              <div className="panel" style={{ marginBottom: 16 }}>
                <h3 style={{ marginTop: 0 }}>Time series</h3>
                {series ? (
                  <SensorChart
                    points={series.times.map((t, i) => ({ t, v: series.values[i] }))}
                    anomalies={(anoms?.events ?? []).map((e) => ({ ts: e.ts, value: e.value }))}
                    threshold={{ gt: gt !== "" ? Number(gt) : null, lt: lt !== "" ? Number(lt) : null }}
                    downsampled={series.downsampled}
                    unit={detail.channels.find((c) => c.name === channel)?.unit}
                  />
                ) : <div style={{ color: "var(--muted)" }}>Loading series…</div>}
              </div>

              {canWrite && (
                <div className="panel" style={{ marginBottom: 16 }}>
                  <h3 style={{ marginTop: 0 }}>Analysis</h3>
                  <div className="grid grid-3">
                    <div className="field">
                      <label>METHOD</label>
                      <select value={method} onChange={(e) => setMethod(e.target.value)} style={selStyle}>
                        <option value="rolling_zscore">rolling_zscore</option>
                        <option value="zscore">zscore</option>
                        <option value="iqr">iqr</option>
                        <option value="threshold">threshold</option>
                      </select>
                    </div>
                    <div className="field"><label>WINDOW</label><input type="number" value={window} onChange={(e) => setWindow(Number(e.target.value))} /></div>
                    <div className="field"><label>THRESHOLD (Z)</label><input type="number" step="0.1" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} /></div>
                    <div className="field"><label>GT (OPTIONAL)</label><input value={gt} onChange={(e) => setGt(e.target.value)} placeholder="e.g. 5.0" /></div>
                    <div className="field"><label>LT (OPTIONAL)</label><input value={lt} onChange={(e) => setLt(e.target.value)} placeholder="e.g. 0.5" /></div>
                    <div className="field">
                      <label>COMPARE CHANNEL</label>
                      <select value={cmpCh} onChange={(e) => setCmpCh(e.target.value)} style={selStyle}>
                        <option value="">None</option>
                        {detail.channels.filter((c) => c.name !== channel).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                      </select>
                    </div>
                    <div className="field"><label>EVENT START</label><input type="datetime-local" value={evStart} onChange={(e) => setEvStart(e.target.value)} /></div>
                    <div className="field"><label>EVENT END</label><input type="datetime-local" value={evEnd} onChange={(e) => setEvEnd(e.target.value)} /></div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button className="btn btn-ghost" onClick={runAnalyze} disabled={busy}>Run analysis</button>
                    <button className="btn btn-ghost" onClick={runFreq} disabled={busy}>Frequency (FFT)</button>
                    <button className="btn btn-ghost" onClick={runCorr} disabled={busy || !cmpCh}>Correlate</button>
                  </div>
                  {method === "threshold" && gt === "" && lt === "" && (
                    <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>No configured engineering threshold.</div>
                  )}
                </div>
              )}

              {stats && (
                <div className="panel" style={{ marginBottom: 16 }}>
                  <h3 style={{ marginTop: 0 }}>Statistics &amp; trend</h3>
                  <div className="grid grid-3">
                    {[["n", stats.n], ["min", stats.min], ["max", stats.max], ["mean", stats.mean],
                      ["median", stats.median], ["std", stats.std], ["rms", stats.rms],
                      ["peak", stats.peak], ["peak-to-peak", stats.peak_to_peak],
                      ["crest factor", stats.crest_factor]].map(([k, v]) => (
                      <div key={k as string} className="kv"><span>{String(k).toUpperCase()}</span>
                        <span>{v === null || v === undefined ? "—" : Number(v).toFixed(4)}</span></div>
                    ))}
                  </div>
                  {analysis !== null && (analysis as { trend?: { direction?: string } }).trend && (
                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      Trend: <b>{(analysis as { trend: { direction: string } }).trend.direction}</b>
                    </div>
                  )}
                  {anoms && (
                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      {anoms.note ? anoms.note : (
                        <>Statistical anomalies detected: <b>{anoms.count}</b> (method {anoms.method}). This is a statistical observation and does not by itself establish equipment failure.</>
                      )}
                    </div>
                  )}
                  {(analysis as { event?: { anomalies_in_window?: number } } | null)?.event && (
                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      Event window anomalies: <b>{(analysis as { event: { anomalies_in_window: number } }).event.anomalies_in_window}</b>
                    </div>
                  )}
                  {(analysis as { correlation?: { r?: number | null; n?: number; note?: string } } | null)?.correlation && (
                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      Correlation observed: r = <b>{String((analysis as { correlation: { r: number | null } }).correlation.r ?? "n/a")}</b>
                      {" "}({(analysis as { correlation: { note?: string } }).correlation.note})
                    </div>
                  )}
                </div>
              )}

              {freq !== null && (
                <div className="panel" style={{ marginBottom: 16 }}>
                  <h3 style={{ marginTop: 0 }}>Frequency analysis (FFT)</h3>
                  {(freq as { available?: boolean; reason?: string }).available === false ? (
                    <div className="alert alert-warn">{String((freq as { reason?: string }).reason)}</div>
                  ) : (
                    <>
                      <div className="kv"><span>SAMPLE RATE</span><span>{String((freq as { sample_rate_hz?: number }).sample_rate_hz)} Hz</span></div>
                      {((freq as { peaks?: { frequency_hz: number; amplitude: number }[] }).peaks ?? []).map((p, i) => (
                        <div className="kv" key={i}><span>PEAK {i + 1}</span><span>{p.frequency_hz} Hz · amp {p.amplitude}</span></div>
                      ))}
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
                        {(freq as { limitation?: string }).limitation}
                      </div>
                    </>
                  )}
                </div>
              )}

              {corr !== null && (corr as { r?: number | null }).r !== null && (
                <div className="panel" style={{ marginBottom: 16 }}>
                  <h3 style={{ marginTop: 0 }}>Correlation</h3>
                  <div className="kv"><span>PEARSON r</span><span>{String((corr as { r: number }).r)} (n={(corr as { n: number }).n})</span></div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>Correlation observed, not causation.</div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
