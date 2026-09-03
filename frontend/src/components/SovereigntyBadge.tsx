import { useEffect, useState } from "react";
import { api } from "../api";

/** Live sovereignty badge — renders ONLY what /api/sovereignty reports. */
export default function SovereigntyBadge() {
  const [model, setModel] = useState<string>("…");
  const [blocked, setBlocked] = useState(true);

  useEffect(() => {
    api.sovereignty()
      .then((s) => {
        setModel(String(s.ai_active_model ?? "none"));
        setBlocked(s.external_ai === "BLOCKED");
      })
      .catch(() => setModel("unreachable"));
  }, []);

  return (
    <div className="badge" title="Live from /api/sovereignty">
      <span className={`dot ${model !== "none" && model !== "unreachable" ? "dot-online" : "dot-offline"}`} />
      <span>MODEL: {model.toUpperCase()}</span>
      <span>·</span>
      <span>EXT-AI: {blocked ? "BLOCKED" : "OPEN"}</span>
    </div>
  );
}
