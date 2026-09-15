import { useState } from "react";
import { api } from "../api";

const PRESETS = ["auto", "fast", "balanced", "high_quality", "max_quality"];
const LANGUAGES = ["zh-CN", "en-US", "ja-JP"];

export default function NewProject({ onCreated }: { onCreated: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [language, setLanguage] = useState("zh-CN");
  const [preset, setPreset] = useState("auto");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!prompt.trim()) {
      setError("Describe what you want to make first.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.createProject({ prompt, language, preset });
      setMessage(`Project ${result.id} created with ${result.scenes} scenes. Rendering…`);
      const job = await api.generate(result.id, preset);
      setMessage(`Job ${job.job_id} queued. Switching to Projects.`);
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">New Project</h1>
      <p className="page-sub">What do you want to make?</p>

      {error && <div className="error">{error}</div>}
      {message && <div className="card" style={{ marginBottom: 16 }}>{message}</div>}

      <div className="card" style={{ maxWidth: 720 }}>
        <div className="field">
          <label>Prompt</label>
          <textarea
            placeholder="做一个 60 秒视频，介绍为什么 AI Agent 会改变软件开发。希望科技感，但不要 AI 味太重。"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </div>

        <div className="grid cols-2">
          <div className="field">
            <label>Language</label>
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {LANGUAGES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Quality</label>
            <select value={preset} onChange={(event) => setPreset(event.target.value)}>
              {PRESETS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button className="ghost" onClick={() => setAdvanced((value) => !value)}>
          {advanced ? "Hide advanced" : "Advanced options"}
        </button>
        {advanced && (
          <div className="card" style={{ marginTop: 12, background: "var(--panel-2)" }}>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
              Advanced provider locking and Expert Mode arrive in P1. Foundation exposes the
              API fields already — the Studio UI for them is intentionally not built yet.
            </p>
          </div>
        )}

        <button
          className="primary"
          style={{ marginTop: 18 }}
          onClick={submit}
          disabled={busy}
        >
          {busy ? "Working…" : "Create & Render"}
        </button>
        <span style={{ marginLeft: 12, color: "var(--muted)", fontSize: 12 }}>
          Plugin-first · task-fit over model size
        </span>
      </div>
    </div>
  );
}
