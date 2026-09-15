/**
 * One prompt in, one MP4 out.
 *
 * This page does exactly one thing the CLI does: it builds a CreateVideoRequest
 * and posts it to /v1/videos. No pipeline logic lives here — if the Studio can
 * do it, the CLI can too, and vice versa.
 */
import { useEffect, useState } from "react";
import {
  api,
  type PlatformPreset,
  type StyleProfile,
  type TemplateManifest,
  type TopicSuggestion,
  type VideoResult,
} from "../api";

type Phase = "idle" | "planning" | "rendering" | "done" | "failed";

export default function Generate() {
  const [prompt, setPrompt] = useState("");
  const [template, setTemplate] = useState("");
  const [style, setStyle] = useState("");
  const [platform, setPlatform] = useState("youtube_16x9");
  const [duration, setDuration] = useState<number | "">("");
  const [scenes, setScenes] = useState<number | "">("");
  const [captions, setCaptions] = useState(true);
  const [strict, setStrict] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const [templates, setTemplates] = useState<TemplateManifest[]>([]);
  const [styles, setStyles] = useState<StyleProfile[]>([]);
  const [platforms, setPlatforms] = useState<PlatformPreset[]>([]);
  const [topics, setTopics] = useState<TopicSuggestion[]>([]);
  const [suggesting, setSuggesting] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<VideoResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    api.templates().then(setTemplates).catch(() => setTemplates([]));
    api.styles().then(setStyles).catch(() => setStyles([]));
    api.platforms().then(setPlatforms).catch(() => setPlatforms([]));
  }, []);

  // A render takes tens of seconds; a ticking clock is the difference between
  // "working" and "hung" from the user's side of the screen.
  useEffect(() => {
    if (phase !== "rendering") return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed((Date.now() - started) / 1000), 250);
    return () => window.clearInterval(timer);
  }, [phase]);

  const suggest = async () => {
    if (!prompt.trim()) return;
    setSuggesting(true);
    try {
      setTopics(await api.suggestTopics(prompt, 5));
    } catch {
      setTopics([]);
    } finally {
      setSuggesting(false);
    }
  };

  const generate = async () => {
    if (!prompt.trim()) {
      setError("Type what the video should be about.");
      setPhase("failed");
      return;
    }
    setError(null);
    setResult(null);
    setTopics([]);
    setElapsed(0);
    setPhase(dryRun ? "planning" : "rendering");
    try {
      const body = {
        prompt,
        template: template || undefined,
        style: style || undefined,
        platform,
        duration_sec: duration === "" ? undefined : Number(duration),
        scenes: scenes === "" ? undefined : Number(scenes),
        captions,
        strict,
        dry_run: dryRun,
        created_by: "studio" as const,
        wait: true,
      };
      const response = await api.createVideo(body);
      setResult(response);
      setPhase(response.ok ? "done" : "failed");
      if (!response.ok) setError(response.error ?? "generation failed");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("failed");
    }
  };

  const busy = phase === "planning" || phase === "rendering";
  const expectedTemplates = templates.filter((item) =>
    !duration || Number(duration) >= item.scene_count.min * 3,
  );

  return (
    <div className="page">
      <header className="page-head">
        <h2>Generate</h2>
        <p className="muted">
          One prompt in. A complete MP4 out. Everything below is optional.
        </p>
      </header>

      <div className="grid-2">
        <section className="card">
          <label className="field">
            <span>What is the video about?</span>
            <textarea
              rows={3}
              value={prompt}
              placeholder="e.g. explain why CI pipelines get slower as they grow"
              onChange={(event) => setPrompt(event.target.value)}
              disabled={busy}
            />
          </label>

          <div className="row">
            <button className="btn" onClick={suggest} disabled={busy || suggesting}>
              {suggesting ? "Thinking…" : "Suggest angles"}
            </button>
            <span className="muted small">offline · deterministic · no model needed</span>
          </div>

          {topics.length > 0 && (
            <ul className="topic-list">
              {topics.map((item) => (
                <li key={`${item.angle}-${item.title}`}>
                  <button
                    className="link"
                    onClick={() => setPrompt(item.title)}
                    title={item.rationale}
                  >
                    {item.title}
                  </button>
                  <span className="muted small">
                    {" "}
                    {item.angle} · {item.video_type} · {item.score.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="grid-3">
            <label className="field">
              <span>Template</span>
              <select value={template} onChange={(e) => setTemplate(e.target.value)}>
                <option value="">auto (ranked)</option>
                {expectedTemplates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Style</span>
              <select value={style} onChange={(e) => setStyle(e.target.value)}>
                <option value="">auto (template default)</option>
                {styles.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Platform</span>
              <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
                {platforms.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} · {item.aspect}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid-3">
            <label className="field">
              <span>Duration (s)</span>
              <input
                type="number"
                min={5}
                value={duration}
                placeholder="auto"
                onChange={(e) =>
                  setDuration(e.target.value === "" ? "" : Number(e.target.value))
                }
              />
            </label>
            <label className="field">
              <span>Scenes</span>
              <input
                type="number"
                min={1}
                value={scenes}
                placeholder="auto"
                onChange={(e) =>
                  setScenes(e.target.value === "" ? "" : Number(e.target.value))
                }
              />
            </label>
            <div className="field">
              <span>Options</span>
              <label className="check">
                <input
                  type="checkbox"
                  checked={captions}
                  onChange={(e) => setCaptions(e.target.checked)}
                />
                Captions
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={strict}
                  onChange={(e) => setStrict(e.target.checked)}
                />
                Strict QC
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(e) => setDryRun(e.target.checked)}
                />
                Plan only
              </label>
            </div>
          </div>

          <button className="btn primary wide" onClick={generate} disabled={busy}>
            {busy ? "Generating…" : "Generate video"}
          </button>
          {busy && (
            <p className="muted small">
              {phase === "planning" ? "Planning" : "Rendering"} · {elapsed.toFixed(0)}s
              elapsed. Rendering is CPU-bound; a 20s video typically takes 1–3 minutes.
            </p>
          )}
        </section>

        <section className="card">
          <h3>Result</h3>
          {phase === "idle" && <p className="muted">Nothing generated yet.</p>}
          {error && <p className="error">{error}</p>}

          {result && (
            <>
              <div className="kv">
                <span>Status</span>
                <b className={result.ok ? "ok" : "fail"}>
                  {result.ok ? "OK" : result.error_code ?? "FAILED"}
                </b>
              </div>
              {result.video_path && (
                <div className="kv">
                  <span>Video</span>
                  <code className="wrap">{result.video_path}</code>
                </div>
              )}
              <div className="kv">
                <span>Scenes</span>
                <b>{result.scenes}</b>
              </div>
              {result.duration_sec !== null && (
                <div className="kv">
                  <span>Duration</span>
                  <b>{result.duration_sec.toFixed(1)}s</b>
                </div>
              )}
              <div className="kv">
                <span>Template</span>
                <b>
                  {result.template ?? "—"} / {result.style ?? "—"}
                </b>
              </div>
              {result.elapsed_sec !== null && (
                <div className="kv">
                  <span>Elapsed</span>
                  <b>{result.elapsed_sec.toFixed(1)}s</b>
                </div>
              )}
              {result.qc && (
                <div className="kv">
                  <span>QC</span>
                  <b className={result.qc.passed ? "ok" : "fail"}>
                    {result.qc.passed ? "PASS" : "FAIL"}
                  </b>
                </div>
              )}

              {result.warnings.length > 0 && (
                <>
                  <h4>Warnings</h4>
                  <ul className="tight">
                    {result.warnings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </>
              )}
              {result.fallbacks.length > 0 && (
                <>
                  <h4>Fallbacks</h4>
                  <ul className="tight">
                    {result.fallbacks.map((item, index) => (
                      <li key={index}>
                        {item.stage}: {item.from} → {item.to}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {result.reasons.length > 0 && (
                <details>
                  <summary>Why these choices ({result.reasons.length})</summary>
                  <ul className="tight">
                    {result.reasons.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
