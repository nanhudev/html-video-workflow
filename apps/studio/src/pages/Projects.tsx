import { useEffect, useRef, useState } from "react";
import { api, JobView, ProjectSummary } from "../api";

const STATUS_CLASS: Record<string, string> = {
  completed: "ok",
  running: "warn",
  planning: "warn",
  queued: "neutral",
  failed: "fail",
  cancelled: "neutral",
  paused: "neutral",
};

export default function Projects() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selected, setSelected] = useState<ProjectSummary | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const load = () => {
    api
      .projects()
      .then((items) => {
        setProjects(items);
        if (selected) {
          const fresh = items.find((item) => item.id === selected.id);
          if (fresh) setSelected(fresh);
        }
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll the active job until it reaches a terminal state.
  useEffect(() => {
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) {
      if (timer.current) window.clearInterval(timer.current);
      return;
    }
    timer.current = window.setInterval(async () => {
      try {
        const next = await api.job(job.id);
        setJob(next);
        load();
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status]);

  const generate = async (project: ProjectSummary) => {
    setBusy(true);
    setError(null);
    try {
      const { job_id } = await api.generate(project.id);
      setJob(await api.job(job_id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!job) return;
    await api.cancelJob(job.id).catch(() => undefined);
    setJob(await api.job(job.id).catch(() => null));
  };

  return (
    <div>
      <h1 className="page-title">Projects</h1>
      <p className="page-sub">Inspect a project, run it, and watch every stage.</p>
      {error && <div className="error">{error}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h3>Project library</h3>
          {projects.length ? (
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Scenes</th>
                  <th>Lang</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {projects.map((project) => (
                  <tr key={project.id}>
                    <td>
                      <a
                        href="#projects"
                        onClick={(event) => {
                          event.preventDefault();
                          setSelected(project);
                        }}
                      >
                        {project.title.slice(0, 40)}
                      </a>
                      <div style={{ fontSize: 11, color: "var(--muted)" }}>{project.id}</div>
                    </td>
                    <td>{project.scene_count}</td>
                    <td>{project.language}</td>
                    <td>
                      <button
                        className="ghost"
                        onClick={() => generate(project)}
                        disabled={busy}
                      >
                        Generate
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">No projects yet — create one first.</div>
          )}
        </div>

        <div className="card">
          <h3>Job</h3>
          {!job && <div className="empty">No active job. Pick a project and press Generate.</div>}
          {job && (
            <>
              <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
                <span className={`pill ${STATUS_CLASS[job.status] ?? "neutral"}`}>
                  {job.status.toUpperCase()}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{job.id}</span>
                <span style={{ marginLeft: "auto" }}>{Math.round(job.progress * 100)}%</span>
              </div>
              <div className="progress" style={{ marginBottom: 14 }}>
                <div style={{ width: `${Math.round(job.progress * 100)}%` }} />
              </div>

              <table>
                <tbody>
                  <tr>
                    <td>Preset</td>
                    <td>{job.plan.preset}</td>
                  </tr>
                  <tr>
                    <td>LLM</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{job.plan.llm ?? "—"}</td>
                  </tr>
                  <tr>
                    <td>TTS</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{job.plan.tts ?? "—"}</td>
                  </tr>
                  <tr>
                    <td>Renderer</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{job.plan.renderer ?? "—"}</td>
                  </tr>
                </tbody>
              </table>

              <h3 style={{ marginTop: 16 }}>Stages</h3>
              {job.tasks.map((task) => (
                <div key={task.stage} style={{ marginBottom: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <b>{task.stage}</b>
                    <span style={{ color: "var(--muted)" }}>
                      {task.status} · {Math.round(task.progress * 100)}%
                    </span>
                  </div>
                  <div className="progress" style={{ marginTop: 4 }}>
                    <div style={{ width: `${Math.round(task.progress * 100)}%` }} />
                  </div>
                  {task.steps.some((step) => step.error) && (
                    <div className="error" style={{ marginTop: 6 }}>
                      {task.steps.find((step) => step.error)?.error}
                    </div>
                  )}
                </div>
              ))}

              {job.fallbacks.length > 0 && (
                <>
                  <h3 style={{ marginTop: 16 }}>Fallbacks used</h3>
                  <ul style={{ paddingLeft: 18, fontSize: 13, color: "var(--warn)" }}>
                    {job.fallbacks.map((item, index) => (
                      <li key={index}>
                        {item.stage}: {item.from} → {item.to} ({item.reason})
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {job.quality && (
                <>
                  <h3 style={{ marginTop: 16 }}>Quality</h3>
                  <p style={{ margin: 0 }}>
                    <span className={`pill ${job.quality.passed ? "ok" : "fail"}`}>
                      {job.quality.passed ? "PASSED" : "FAILED"}
                    </span>
                    {job.quality.warned.length > 0 && (
                      <span style={{ marginLeft: 8, color: "var(--warn)", fontSize: 12 }}>
                        warnings: {job.quality.warned.join(", ")}
                      </span>
                    )}
                  </p>
                  <ul style={{ paddingLeft: 18, fontSize: 12, color: "var(--muted)" }}>
                    {job.quality.checks.map((check) => (
                      <li key={check.name}>
                        <b>{check.name}</b>: {check.status} — {check.detail}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {job.outputs.video && (
                <p style={{ fontSize: 12, fontFamily: "var(--mono)", wordBreak: "break-all" }}>
                  {job.outputs.video}
                </p>
              )}

              <button className="ghost" onClick={cancel} disabled={job.status !== "running"}>
                Cancel job
              </button>
            </>
          )}
        </div>
      </div>

      {selected && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3>{selected.title}</h3>
          <dl className="kv">
            <dt>Project id</dt>
            <dd>{selected.id}</dd>
            <dt>Scenes</dt>
            <dd>{selected.scene_count}</dd>
            <dt>Language</dt>
            <dd>{selected.language}</dd>
            <dt>Updated</dt>
            <dd>{selected.updated_at}</dd>
            <dt>Manifest</dt>
            <dd>{selected.path}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}
