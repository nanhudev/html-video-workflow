import { useEffect, useState } from "react";
import { api, HardwareProfile, ProjectSummary, RoutingInfo, SystemInfo } from "../api";

interface Props {
  onNavigate: (route: "home" | "projects" | "new" | "providers" | "hardware" | "settings") => void;
}

export default function Dashboard({ onNavigate }: Props) {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [hardware, setHardware] = useState<HardwareProfile | null>(null);
  const [routing, setRouting] = useState<RoutingInfo | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.system(), api.hardware(), api.routing(), api.projects()])
      .then(([s, h, r, p]) => {
        setSystem(s);
        setHardware(h);
        setRouting(r);
        setProjects(p.slice(0, 5));
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const gpu = hardware?.gpus?.[0];

  return (
    <div>
      <h1 className="page-title">Home</h1>
      <p className="page-sub">
        Local-first agentic video production runtime — agent decides, IR describes,
        providers execute, quality verifies.
      </p>

      {error && <div className="error">{error}</div>}

      <div className="grid cols-3" style={{ marginBottom: 20 }}>
        <div className="card">
          <h3>Machine</h3>
          <div className="kpi">{gpu?.model ?? "CPU only"}</div>
          <small>
            {hardware?.cpu_model?.slice(0, 34) ?? "—"} ·{" "}
            {hardware ? Math.round((hardware.ram_total_mb ?? 0) / 1024) : "?"} GB RAM
          </small>
        </div>
        <div className="card">
          <h3>Recommended pipeline</h3>
          <div className="kpi">{routing?.preset ?? "…"}</div>
          <small>
            {routing
              ? Object.entries(routing.selection)
                  .map(([stage, id]) => `${stage}:${id ?? "none"}`)
                  .join(" · ")
              : "probing…"}
          </small>
        </div>
        <div className="card">
          <h3>Projects</h3>
          <div className="kpi">{projects.length}</div>
          <small>
            {projects[0] ? `latest: ${projects[0].title.slice(0, 28)}` : "none yet"}
          </small>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Quick start</h3>
          <ol style={{ paddingLeft: 18, margin: 0, lineHeight: 1.9 }}>
            <li>Describe what you want to make.</li>
            <li>Let the runtime pick providers (Auto), or lock one later.</li>
            <li>Watch voice → render → compose → QC in real time.</li>
          </ol>
          <button className="primary" style={{ marginTop: 14 }} onClick={() => onNavigate("new")}>
            New project
          </button>
        </div>

        <div className="card">
          <h3>Runtime</h3>
          <dl className="kv">
            <dt>Version</dt>
            <dd>{system?.version ?? "—"}</dd>
            <dt>Home</dt>
            <dd>{system?.home ?? "—"}</dd>
            <dt>Outputs</dt>
            <dd>{system?.outputs ?? "—"}</dd>
            <dt>Toolchain</dt>
            <dd>
              {hardware
                ? Object.entries(hardware.tooling)
                    .map(([name, tool]) => `${name}${tool.available ? "✓" : "✗"}`)
                    .join(" ")
                : "—"}
            </dd>
          </dl>
        </div>
      </div>
    </div>
  );
}
