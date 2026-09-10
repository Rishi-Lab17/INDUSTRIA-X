import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useRole } from "../components/equipment";

const CHUNK_DURATION_MS = 5000; // 5 second chunks

interface Recording {
  id: number;
  title: string;
  status: string;
  started_at: string | null;
  stopped_at: string | null;
  paused_at: string | null;
  duration_seconds: number;
  paused_duration: number;
  equipment_id: number;
  equipment_code?: string;
  investigation_id?: number;
  investigation_title?: string;
  case_id?: number;
  case_number?: string;
  processing_status: string;
  sovereignty_classification: string;
}

export default function LiveInvestigation() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { canWrite: roleCanWrite } = useRole();
  const canWrite = roleCanWrite || (user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER");
  const recId = Number(id);
  
  // Recording state
  const [recording, setRecording] = useState<Recording | null>(null);
  const [status, setStatus] = useState<"idle" | "recording" | "paused" | "processing" | "completed" | "error">("idle");
  const [timer, setTimer] = useState(0);
  const [error, setError] = useState("");
  const [frames, setFrames] = useState<any[]>([]);
  const [interactions, setInteractions] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [evidence, setEvidence] = useState<any[]>([]);
  const [aiQuestion, setAiQuestion] = useState("");
  const [aiAnswer, setAiAnswer] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [showPermissionError, setShowPermissionError] = useState(false);
  
  // Media refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const chunkIndexRef = useRef(0);
  const timerIntervalRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recordingStartTimeRef = useRef<number | null>(null);
  const pausedDurationRef = useRef(0);
  const pauseStartTimeRef = useRef<number | null>(null);

  // Load recording on mount
  useEffect(() => {
    loadRecording();
    return () => cleanup();
  }, []);

  async function loadRecording() {
    try {
      const r = await api.recordingGet(recId) as unknown as Recording;
      setRecording(r);
      setStatus((r.status?.toLowerCase() || "idle") as any);
      
      // Load related data
      await Promise.all([
        loadFrames(),
        loadInteractions(),
        loadEvents(),
        loadEvidence(),
      ]);
      
      if (r.status === "RECORDING") {
        startTimer(r.started_at || undefined);
      } else if (r.status === "PAUSED") {
        setTimer(r.duration_seconds || 0);
      } else if (r.status === "PROCESSING" || r.status === "COMPLETED") {
        setTimer(r.duration_seconds || 0);
      }
    } catch (e: any) {
      setError(e.message || "Failed to load recording");
    }
  }

  async function loadFrames() {
    try {
      const r = await api.recordingFrames(recId);
      setFrames(r.frames || []);
    } catch {}
  }

  async function loadInteractions() {
    try {
      const r = await api.recordingInteractions(recId);
      setInteractions(r.interactions || []);
    } catch {}
  }

  async function loadEvents() {
    try {
      const r = await api.recordingEvents(recId);
      setEvents(r.events || []);
    } catch {}
  }

  async function loadEvidence() {
    try {
      const r = await api.recordingEvidenceList(recId);
      setEvidence(r.evidence || []);
    } catch {}
  }

  // Timer management
  function startTimer(startedAt?: string | null) {
    if (timerIntervalRef.current) return;
    
    let baseSeconds = 0;
    if (startedAt) {
      const start = new Date(startedAt).getTime();
      baseSeconds = Math.floor((Date.now() - start) / 1000);
    }
    
    recordingStartTimeRef.current = Date.now() - baseSeconds * 1000;
    setTimer(baseSeconds);
    
    timerIntervalRef.current = window.setInterval(() => {
      setTimer(prev => prev + 1);
    }, 1000);
  }

  function stopTimer() {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
  }

  // Media recording
  async function startRecording() {
    setError("");
    try {
      // Request permissions
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: true,
      });
      
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      
      // Create MediaRecorder
      const options = { mimeType: "video/webm;codecs=vp9" };
      if (!MediaRecorder.isTypeSupported(options.mimeType)) {
        options.mimeType = "video/webm;codecs=vp8";
      }
      if (!MediaRecorder.isTypeSupported(options.mimeType)) {
        options.mimeType = "video/webm";
      }
      
      const recorder = new MediaRecorder(stream, options);
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];
      chunkIndexRef.current = 0;
      
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
          uploadChunk(chunksRef.current.length - 1, e.data);
        }
      };
      
      recorder.onstop = () => {
        // Finalize
        mergeChunks();
      };
      
      // Start recording with 5-second chunks
      recorder.start(CHUNK_DURATION_MS);
      recordingStartTimeRef.current = Date.now();
      setStatus("recording");
      
      // Start timer
      startTimer();
      
      // Notify backend
      await api.recordingStart(recId);
      
    } catch (e: any) {
      if (e.name === "NotAllowedError" || e.name === "PermissionDeniedError") {
        setShowPermissionError(true);
      }
      setError(e.message || "Failed to start recording");
    }
  }

  async function pauseRecording() {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      mediaRecorderRef.current.pause();
      pauseStartTimeRef.current = Date.now();
      setStatus("paused");
      stopTimer();
      pausedDurationRef.current += Date.now() - (recordingStartTimeRef.current || Date.now());
      await api.recordingPause(recId);
    }
  }

  async function resumeRecording() {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "paused") {
      mediaRecorderRef.current.resume();
      setStatus("recording");
      startTimer();
      pausedDurationRef.current += Date.now() - (pauseStartTimeRef.current || Date.now());
      await api.recordingResume(recId);
    }
  }

  async function stopRecording() {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      stopTimer();
      setStatus("processing");
      await api.recordingStop(recId);
    }
  }

  async function uploadChunk(index: number, blob: Blob) {
    try {
      const buf = await blob.arrayBuffer();
      const chunkHash = await sha256(buf);

      const formData = new FormData();
      formData.append("file", blob, `chunk_${chunkIndexRef.current}.webm`);
      formData.append("chunk_index", String(chunkIndexRef.current));
      formData.append("total_chunks", "999");
      formData.append("chunk_sha256", chunkHash);
      formData.append("start_time", String(chunkIndexRef.current * (CHUNK_DURATION_MS / 1000)));
      formData.append("end_time", String((chunkIndexRef.current + 1) * (CHUNK_DURATION_MS / 1000)));

      const token = localStorage.getItem("ix_token");
      await fetch(`/api/recordings/${recId}/chunks`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      chunkIndexRef.current++;
    } catch (e) {
      console.error("Chunk upload failed:", e);
    }
  }

  async function mergeChunks() {
    try {
      await api.recordingMerge(recId);
      setStatus("completed");
      await loadFrames();
      await loadEvidence();
    } catch (e) {
      console.error("Merge failed:", e);
    }
  }

  // Frame capture
  async function captureFrame() {
    if (!videoRef.current || !videoRef.current.videoWidth) {
      setError("No video to capture");
      return;
    }
    
    try {
      const canvas = document.createElement("canvas");
      canvas.width = videoRef.current.videoWidth;
      canvas.height = videoRef.current.videoHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas context unavailable");
      ctx.drawImage(videoRef.current, 0, 0);
      
      const timestamp = (Date.now() - (recordingStartTimeRef.current || Date.now())) / 1000;
      
      const r = await api.recordingFrameCapture(recId, {
        recording_id: recId,
        timestamp_seconds: timestamp,
        capture_type: "MANUAL",
      });
      
      await loadFrames();
      await loadEvidence();
      
    } catch (e: any) {
      setError(e.message || "Failed to capture frame");
    }
  }

  // AI Copilot
  async function askAI() {
    if (!aiQuestion.trim() || aiLoading) return;
    
    const question = aiQuestion;
    setAiQuestion("");
    setAiLoading(true);
    setAiAnswer("");
    
    try {
      const timestamp = (Date.now() - (recordingStartTimeRef.current || Date.now())) / 1000;
      const r = await api.recordingAskAI(recId, {
        recording_id: recId,
        question: aiQuestion,
        recording_timestamp_seconds: Date.now() / 1000,
      }) as { answer?: string };
      
      setAiAnswer(r.answer || "Processing...");
      await loadInteractions();
      
    } catch (e: any) {
      setAiAnswer("Error: " + (e.message || "Failed to get AI response"));
    } finally {
      setAiLoading(false);
    }
  }

  // Evidence capture
  async function captureEvidence() {
    if (!videoRef.current || !videoRef.current.videoWidth) {
      setError("No video to capture");
      return;
    }
    
    try {
      const canvas = document.createElement("canvas");
      canvas.width = videoRef.current.videoWidth;
      canvas.height = videoRef.current.videoHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas context unavailable");
      ctx.drawImage(videoRef.current, 0, 0);
      
      const timestamp = (Date.now() - (recordingStartTimeRef.current || Date.now())) / 1000;
      
      const r = await api.recordingFrameCapture(recId, {
        recording_id: recId,
        timestamp_seconds: timestamp,
        capture_type: "EVENT_TRIGGERED",
      });
      
      const frameId = r.id || (r as any).frame_id;
      
      // Create evidence
      await api.recordingEvidenceCreate(recId, {
        frame_id: r.id,
        title: `Evidence at ${formatTime(timestamp)}`,
        description: `Captured during live investigation`,
      });
      
      await loadFrames();
      await loadEvidence();
      
    } catch (e: any) {
      setError(e.message || "Failed to capture evidence");
    }
  }

  function cleanup() {
    stopTimer();
    if (mediaRecorderRef.current) {
      try { mediaRecorderRef.current.stop(); } catch {}
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => cleanup();
  }, []);

  if (!recording) {
    return <div className="loading">Loading recording…</div>;
  }

  return (
    <div className="live-investigation">
      <header className="live-header">
        <div className="header-left">
          <h1>Live Investigation</h1>
          <div className="context">
            {recording.equipment_code && <span className="badge">{recording.equipment_code}</span>}
            {recording.case_number && <span className="badge case">Case: {recording.case_number}</span>}
            {recording.investigation_title && <span className="badge inv">Inv: {recording.investigation_title}</span>}
          </div>
        </div>
        <div className="header-right">
          <div className={`status-indicator ${status}`}>
            <span className="dot"></span>
            <span className="label">{status.toUpperCase()}</span>
            <span className="timer">{formatTime(timer)}</span>
          </div>
        </div>
      </header>

      {error && <div className="alert alert-error">{error}</div>}
      {showPermissionError && (
        <div className="alert alert-warning">
          Camera/microphone permission denied. Please allow access in browser settings.
          <button onClick={() => setShowPermissionError(false)}>Dismiss</button>
        </div>
      )}

      <main className="live-main">
        <div className="video-section">
          <div className="video-container">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="video-preview"
            />
            {status === "idle" && (
              <div className="video-overlay">
                <button className="btn btn-primary btn-lg" onClick={startRecording} disabled={!canWrite}>
                  <span className="icon">●</span> Start Recording
                </button>
                <p className="hint">Requires camera and microphone permissions</p>
              </div>
            )}
            {status === "recording" && (
              <div className="recording-overlay">
                <div className="recording-indicator">
                  <span className="rec-dot"></span>
                  <span>REC</span>
                  <span className="timer-large">{formatTime(timer)}</span>
                </div>
              </div>
            )}
            {status === "paused" && (
              <div className="paused-overlay">
                <span className="pause-icon">⏸</span>
                <span>PAUSED</span>
                <span>{formatTime(timer)}</span>
              </div>
            )}
          </div>

          <div className="controls">
            {status === "recording" && (
              <>
                <button className="btn btn-warning" onClick={pauseRecording} disabled={!canWrite}>
                  ⏸ Pause
                </button>
                <button className="btn btn-secondary" onClick={captureFrame} disabled={!canWrite}>
                  📸 Capture Frame
                </button>
                <button className="btn btn-primary" onClick={captureEvidence} disabled={!canWrite}>
                  📋 Capture Evidence
                </button>
                <button className="btn btn-danger" onClick={stopRecording} disabled={!canWrite}>
                  ■ Stop
                </button>
              </>
            )}
            {status === "paused" && (
              <>
                <button className="btn btn-success" onClick={resumeRecording} disabled={!canWrite}>
                  ▶ Resume
                </button>
                <button className="btn btn-danger" onClick={stopRecording} disabled={!canWrite}>
                  ■ Stop
                </button>
              </>
            )}
            {status === "idle" && canWrite && (
              <button className="btn btn-primary btn-lg" onClick={startRecording}>
                <span className="icon">●</span> Start Recording
              </button>
            )}
            {status === "processing" && <span className="processing">Processing recording…</span>}
            {status === "completed" && (
              <button className="btn btn-secondary" onClick={() => navigate(`/recordings/${recId}`)}>
                View Recording
              </button>
            )}
          </div>
        </div>

        <aside className="sidebar">
          <div className="panel ai-copilot">
            <h3>AI Copilot</h3>
            <div className="ai-messages">
              {interactions.map((i: any) => (
                <div key={i.id} className="ai-message">
                  <div className="question">
                    <strong>You ({formatTime(i.recording_timestamp_seconds)}):</strong>
                    <p>{i.question}</p>
                  </div>
                  {i.answer && (
                    <div className="answer">
                      <strong>AI:</strong>
                      <p>{i.answer}</p>
                    </div>
                  )}
                </div>
              ))}
              {aiLoading && <div className="ai-loading">AI is thinking…</div>}
            </div>
            <div className="ai-input">
              <input
                type="text"
                value={aiQuestion}
                onChange={e => setAiQuestion(e.target.value)}
                onKeyDown={e => e.key === "Enter" && askAI()}
                placeholder="Ask AI about the investigation…"
                disabled={aiLoading || status !== "recording"}
              />
              <button className="btn btn-primary" onClick={askAI} disabled={aiLoading || !aiQuestion.trim() || status !== "recording"}>
                Ask
              </button>
            </div>
          </div>

          <div className="panel evidence-panel">
            <h3>Captured Evidence</h3>
            {evidence.length === 0 ? (
              <p className="empty">No evidence captured yet</p>
            ) : (
              <ul className="evidence-list">
                {evidence.map((e: any) => (
                  <li key={e.id} className="evidence-item">
                    <strong>{e.evidence_title || e.title}</strong>
                    <span className="time">{formatTime(e.recording_timestamp || 0)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel timeline-panel">
            <h3>Timeline</h3>
            {events.length === 0 ? (
              <p className="empty">No events yet</p>
            ) : (
              <ul className="timeline">
                {events.slice().reverse().map((e: any) => (
                  <li key={e.id} className="timeline-item">
                    <span className="time">{formatTime(e.recording_timestamp_seconds || 0)}</span>
                    <span className="event-type">{e.event_type.replace(/_/g, " ")}</span>
                    {e.payload && typeof e.payload === "object" && (
                      <span className="payload">{JSON.stringify(e.payload).slice(0, 100)}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </main>
    </div>
  );
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

async function sha256(buffer: ArrayBuffer): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}