import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, getToken, type AIMessage, type AIRun, type AISession, type Citation } from "../api";
import { useAuth } from "../auth";

interface RunView {
  status: string;
  answer: string;
  citations: Citation[];
  plan: string[];
  duration_ms: number | null;
  sources_count: number;
  tools_used: string[];
  error?: string;
  streamed: boolean;
}

function StatusDot({ status }: { status: string }) {
  const cls = status === "ONLINE" ? "dot-online"
    : status === "OFFLINE" ? "dot-offline" : "dot-warn";
  return <span className={`dot ${cls}`} />;
}

export default function Workbench() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<AISession[]>([]);
  const [sid, setSid] = useState<number | null>(null);
  const [messages, setMessages] = useState<AIMessage[]>([]);
  const [runs, setRuns] = useState<AIRun[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [health, setHealth] = useState<{ status: string; display: string; is_test: boolean; detail: string } | null>(null);
  const [ragReady, setRagReady] = useState<string>("…");
  const [equipment, setEquipment] = useState<{ id: number; code: string; name: string }[]>([]);
  const [equipId, setEquipId] = useState("");
  const [live, setLive] = useState<RunView | null>(null);
  const [streaming, setStreaming] = useState("");
  const [runId, setRunId] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const refreshSessions = useCallback(() => {
    api.aiSessions().then((r) => setSessions(r.sessions)).catch(() => undefined);
  }, []);

  const loadSession = useCallback((id: number) => {
    setSid(id);
    setLive(null);
    setStreaming("");
    api.aiGetSession(id)
      .then((r) => {
        setMessages(r.messages);
        setRuns(r.runs);
        setEquipId(r.session.equipment_id ? String(r.session.equipment_id) : "");
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  const [devHealth, setDevHealth] = useState<{ status: string; detail: string } | null>(null);

  useEffect(() => {
    refreshSessions();
    api.aiHealth()
      .then((h) => setHealth({ status: h.status, display: h.display, is_test: h.is_test, detail: h.detail }))
      .catch(() => setHealth({ status: "ERROR", display: "AI", is_test: false, detail: "health unreachable" }));
    api.health().then((h) => {
      const svc = (h as { services: Record<string, { status: string; detail: string }> }).services;
      if (svc?.dev_model) setDevHealth(svc.dev_model);
    }).catch(() => setDevHealth(null));
    api.kbHealth()
      .then((h) => setRagReady(h.indexed > 0 ? `READY (${h.indexed} docs)` : "EMPTY"))
      .catch(() => setRagReady("UNAVAILABLE"));
    api.equipmentList().then((r) => setEquipment(r.equipment)).catch(() => setEquipment([]));
  }, [refreshSessions]);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [messages, streaming]);

  async function newSession() {
    setErr("");
    try {
      const s = await api.aiCreateSession(
        equipId ? { equipment_id: Number(equipId) } : {});
      refreshSessions();
      loadSession(s.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function send(useStream: boolean) {
    if (!sid || !input.trim() || busy) return;
    const content = input.trim();
    setInput("");
    setErr("");
    setLive(null);
    setStreaming("");
    setBusy(true);
    // optimistic user bubble
    setMessages((m) => [...m, { id: -Date.now(), role: "USER", content, model: null, created_at: "" }]);
    try {
      if (!useStream) {
        const r = await api.aiSendMessage(sid, { content });
        applyResult(r);
      } else {
        await streamMessage(sid, content);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Send failed");
    } finally {
      setBusy(false);
      abortRef.current = null;
      refreshSessions();
      if (sid) {
        api.aiGetSession(sid)
          .then((r) => {
            setMessages(r.messages);
            setRuns(r.runs);
          })
          .catch(() => undefined);
      }
    }
  }

  function applyResult(r: RunView & { run_id: number }) {
    setRunId(r.run_id);
    setLive(r);
  }

  async function streamMessage(sessionId: number, content: string) {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const t = getToken();
    const res = await fetch(`/api/ai/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 ...(t ? { Authorization: `Bearer ${t}` } : {}) },
      body: JSON.stringify({ content }),
      signal: ctrl.signal,
    });
    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({}));
      const d = (data as { detail?: unknown }).detail;
      const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: unknown) => (x as { msg?: string }).msg || String(x)).join("; ") : d && typeof d === "object" && "message" in (d as Record<string,unknown>) ? String((d as Record<string,unknown>).message) : `Stream failed (${res.status})`;
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let donePayload = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const evMatch = frame.match(/^event: (\w+)\ndata: ([\s\S]*)$/);
        if (!evMatch) continue;
        const [, ev, data] = evMatch;
        if (ev === "token") {
          try {
            setStreaming((s) => s + (JSON.parse(data) as string));
          } catch { /* ignore malformed frame */ }
        } else if (ev === "error") {
          throw new Error(JSON.parse(data) as string);
        } else if (ev === "done") {
          donePayload = data;
        }
      }
    }
    if (donePayload) {
      const r = JSON.parse(donePayload);
      setRunId(r.run_id ?? null);
      setLive(r);
    }
    setStreaming("");
  }

  async function cancel() {
    abortRef.current?.abort();
    if (runId) {
      try {
        await api.aiCancelRun(runId);
      } catch { /* run may already be finished */ }
    }
    setBusy(false);
  }

  const offline = health?.status !== "ONLINE";

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">AI Workbench</h1>
          <p className="page-sub">Grounded industrial assistance — evidence first, never faked.</p>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 13, alignItems: "center" }}>
          <span>
            PRIMARY: <b>Kimi K3</b> {health && <StatusDot status={health.status} />} {health?.status ?? "…"}
            {health?.is_test && <span className="badge" style={{ marginLeft: 8 }}>TEST ONLY</span>}
          </span>
          <span>
            DEV MODEL: <b>Ollama</b> {devHealth && <StatusDot status={devHealth.status} />} {devHealth?.status ?? "…"}
            <span style={{ color: "var(--muted)", marginLeft: 6 }}>{devHealth?.detail?.slice(0, 60) ?? ""}</span>
          </span>
          <span>Knowledge: <b>{ragReady}</b></span>
          <span>External AI: <b>BLOCKED</b> (sovereignty)</span>
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
          PRIMARY KIMI K3 = <span className="mono">{health?.display ?? "kimi-k3"}</span> at <span className="mono">http://127.0.0.1:11436/v1</span> (2.8T, datacenter) · DEV MODEL = <span className="mono">Ollama</span> at <span className="mono">http://127.0.0.1:11434</span> (labelled, never Kimi) · External AI is sovereignty-blocked, no silent fallback.
        </div>
        {offline && health && (
          <div className="alert alert-warn" style={{ marginTop: 12, marginBottom: 0 }}>
            <b>PRIMARY KIMI K3 is unavailable</b>: {health.detail} Retrieval, RAG, and investigations still work; answers cannot be generated until a local model is connected. If <b>DEV MODEL Ollama</b> is {devHealth?.status === "ONLINE" ? "ONLINE" : "also OFFLINE"} — {devHealth?.detail ?? "Ollama not running"} — start it via <span className="mono">ollama run hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M</span> to enable the labelled dev model (never reported as Kimi K3).
          </div>
        )}
      </div>

      {err && <div className="alert alert-error">{err}</div>}

      <div className="grid grid-2" style={{ gridTemplateColumns: "280px 1fr" }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Sessions</h3>
          <div className="field">
            <label>EQUIPMENT FOR NEW SESSION</label>
            <select value={equipId} onChange={(e) => setEquipId(e.target.value)} style={selStyle}>
              <option value="">No equipment</option>
              {equipment.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.name}</option>)}
            </select>
          </div>
          <button className="btn btn-ghost" style={{ width: "100%", marginBottom: 12 }} onClick={newSession}>
            + New session
          </button>
          {sessions.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--muted)" }}>No sessions yet.</div>
          )}
          {sessions.map((s) => (
            <div key={s.id}
              onClick={() => loadSession(s.id)}
              style={{
                padding: "8px 10px", borderRadius: 8, cursor: "pointer", marginBottom: 6,
                border: "1px solid var(--border)",
                background: sid === s.id ? "rgba(0,166,199,.14)" : "transparent",
              }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>{s.title}</div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{s.provider}/{s.model}</div>
            </div>
          ))}
        </div>

        <div className="panel">
          {!sid ? (
            <div style={{ color: "var(--muted)" }}>Select or create a session to begin.</div>
          ) : (
            <>
              <div ref={boxRef} style={{ maxHeight: 420, overflowY: "auto", marginBottom: 12 }}>
                {messages.map((m) => (
                  <div key={m.id} style={{
                    marginBottom: 10, padding: 10, borderRadius: 8,
                    background: m.role === "USER" ? "rgba(22,119,183,.15)" : "rgba(0,166,199,.08)",
                    border: "1px solid var(--border)",
                  }}>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>{m.role}</div>
                    <div style={{ whiteSpace: "pre-wrap", fontSize: 14 }}>{m.content}</div>
                  </div>
                ))}
                {streaming && (
                  <div style={{ padding: 10, borderRadius: 8, background: "rgba(0,166,199,.08)", border: "1px solid var(--border)", marginBottom: 10 }}>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>ASSISTANT · generating</div>
                    <div style={{ whiteSpace: "pre-wrap", fontSize: 14 }}>{streaming}▍</div>
                  </div>
                )}
              </div>

              {live && <RunCard run={live} />}

              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(true); } }}
                  placeholder="Ask about your private documents… (Enter to send, streamed)"
                  aria-label="AI question"
                  style={{ flex: 1, padding: 11, borderRadius: 8, border: "1px solid var(--border)", background: "#F8FAFC", color: "var(--text)" }}
                  disabled={busy}
                />
                <button className="btn btn-ghost" onClick={() => send(true)} disabled={busy || !input.trim()}>Send</button>
                <button className="btn btn-ghost" onClick={() => send(false)} disabled={busy || !input.trim()} title="Non-streamed request">Send once</button>
                {busy && <button className="btn btn-ghost" onClick={cancel}>Stop</button>}
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
                Signed in as {user?.role}. Evidence is company-scoped; citations are preserved, never invented.
              </div>
            </>
          )}
        </div>
      </div>

      {runs.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Recent runs (replay metadata)</h3>
          <table className="table">
            <thead><tr><th>ID</th><th>Status</th><th>Task</th><th>Duration</th><th>Sources</th><th>Tools</th></tr></thead>
            <tbody>
              {runs.map((r) => {
                let tools: string;
                try {
                  const v: unknown = (r as unknown as Record<string, unknown>).tools_used;
                  tools = Array.isArray(v) ? (v as string[]).join(", ") : String(v ?? "—");
                } catch {
                  tools = "—";
                }
                return (
                  <tr key={r.id}>
                    <td>{r.id}</td><td>{r.status}</td><td>{r.task_type}</td>
                    <td>{r.duration_ms !== null ? `${r.duration_ms}ms` : "—"}</td>
                    <td>{r.sources_count}</td><td>{tools}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RunCard({ run }: { run: RunView }) {
  if (run.status === "UNAVAILABLE") {
    return <div className="alert alert-warn">{run.error ?? "Model unavailable."} Evidence (if any) is listed below; no answer was fabricated.</div>;
  }
  if (run.status === "FAILED" || run.status === "TIMEOUT") {
    return <div className="alert alert-error">{run.error ?? "AI run failed."} (category recorded, no stack trace exposed)</div>;
  }
  if (run.status === "CANCELLED") {
    return <div className="alert alert-warn">Run cancelled. Partial work was discarded.</div>;
  }
  return (
    <div className="panel" style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>AI RUN · COMPLETED</div>
      <div style={{ whiteSpace: "pre-wrap", fontSize: 14, marginBottom: 8 }}>{run.answer}</div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>Actions:</div>
      <div style={{ fontSize: 13, marginBottom: 6 }}>✓ Knowledge Base searched · ✓ {run.sources_count} source(s) retrieved · ✓ Response generated</div>
      {run.plan.length > 0 && (
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
          Plan: {run.plan.join(" → ")}
        </div>
      )}
      {run.citations.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Sources (evidence, not chain-of-thought):</div>
          {run.citations.map((c) => (
            <div key={c.chunk_id} className="kv">
              <span>{c.filename} v{c.document_version}{c.page ? ` p.${c.page}` : ""}{c.section ? ` · ${c.section}` : ""}</span>
              <span>{c.retrieval_method} · {c.combined_score}</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
        {run.duration_ms !== null ? `${run.duration_ms}ms` : ""} · tools: {run.tools_used.join(", ") || "none"}
        {run.streamed ? " · streamed" : ""}
      </div>
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#F8FAFC",
  color: "var(--text)", border: "1px solid var(--border)",
};
