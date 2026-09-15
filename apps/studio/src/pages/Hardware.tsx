import { useEffect, useState } from "react";
import { api, HardwareProfile, RoutingInfo } from "../api";

const PRESETS = ["auto", "fast", "balanced", "high_quality", "max_quality"];

export default function Hardware() {
  const [profile, setProfile] = useState<HardwareProfile | null>(null);
  const [routing, setRouting] = useState<RoutingInfo | null>(null);
  const [preset, setPreset] = useState("auto");
  const [benchmark, setBenchmark] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = (refresh = false) => {
    api
      .hardware(refresh)
      .then(setProfile)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    load();
    api
      .routing()
      .then(setRouting)
      .catch(() => setRouting(null));
  }, []);

  useEffect(() => {
    api
      .routing(preset)
      .then(setRouting)
      .catch(() => setRouting(null));
  }, [preset]);

  const refresh = () => {
    load(true);
    api
      .routing(preset)
      .then(setRouting)
      .catch(() => setRouting(null));
  };

  const runBenchmark = async () => {
    setBenchmark("running…");
    try {
      const result = await fetch("/benchmarks/run", { method: "POST" }).then((r) => r.json());
      setBenchmark(JSON.stringify(result, null, 2));
    } catch (err) {
      setBenchmark(`failed: ${(err as Error).message}`);
    }
  };

  return (
    <div>
      <h1 className="page-title">Hardware</h1>
      <p className="page-sub">
        Everything below comes from a live probe — nothing is hardcoded and nothing is
        guessed.
      </p>
      {error && <div className="error">{error}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h3>System</h3>
          <dl className="kv">
            <dt>OS</dt>
            <dd>
              {profile?.os} {profile?.os_version?.slice(0, 20)} ({profile?.arch})
            </dd>
            <dt>CPU</dt>
            <dd>{profile?.cpu_model ?? "unknown"}</dd>
            <dt>Cores</dt>
            <dd>{profile?.cpu_logical_cores ?? "—"} logical</dd>
            <dt>RAM</dt>
            <dd>
              {profile ? ((profile.ram_total_mb ?? 0) / 1024).toFixed(1) : "—"} GB total ·{" "}
              {profile ? ((profile.ram_free_mb ?? 0) / 1024).toFixed(1) : "—"} GB free
            </dd>
            <dt>Disk free</dt>
            <dd>{profile ? `${((profile.disk_free_mb ?? 0) / 1024).toFixed(1)} GB` : "—"}</dd>
            <dt>Probed</dt>
            <dd>{profile?.probed_at ?? "—"}</dd>
          </dl>
          <button className="ghost" style={{ marginTop: 12 }} onClick={refresh}>
            Re-probe
          </button>
        </div>

        <div className="card">
          <h3>GPUs</h3>
          {profile?.gpus?.length ? (
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Vendor</th>
                  <th>VRAM</th>
                  <th>Driver</th>
                </tr>
              </thead>
              <tbody>
                {profile.gpus.map((gpu, index) => (
                  <tr key={index}>
                    <td>{gpu.model ?? gpu.vendor}</td>
                    <td>{gpu.vendor}</td>
                    <td>{gpu.vram_mb ? `${(gpu.vram_mb / 1024).toFixed(1)} GB` : "unknown"}</td>
                    <td>{gpu.driver_version ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">No GPU detected — CPU-only pipeline.</div>
          )}

          <h3 style={{ marginTop: 18 }}>Acceleration</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {Object.entries(profile?.accelerators ?? {}).map(([key, value]) => (
              <span
                key={key}
                className={`pill ${value ? "ok" : value === false ? "neutral" : "warn"}`}
              >
                {key}: {value === null ? "n/a" : value ? "yes" : "no"}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Toolchain</h3>
        <table>
          <thead>
            <tr>
              <th>Tool</th>
              <th>Status</th>
              <th>Version</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(profile?.tooling ?? {}).map(([name, tool]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>
                  <span className={`pill ${tool.available ? "ok" : "fail"}`}>
                    {tool.available ? "OK" : "MISSING"}
                  </span>
                </td>
                <td>{(tool.version ?? "—").slice(0, 48)}</td>
                <td style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
                  {tool.path ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Recommended pipeline</h3>
        <div className="field" style={{ maxWidth: 260 }}>
          <label>Preset</label>
          <select value={preset} onChange={(event) => setPreset(event.target.value)}>
            {PRESETS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        {routing ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Selected</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(routing.selection).map(([stage, id]) => {
                  const chosen = routing.reasons[stage]?.candidates?.find((c) => c.chosen);
                  return (
                    <tr key={stage}>
                      <td>{stage}</td>
                      <td>{id ?? <span className="pill fail">none</span>}</td>
                      <td style={{ color: "var(--muted)" }}>
                        {chosen?.reason.join(" · ") ?? "no provider available"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 10 }}>
              Preset chosen by the profiler: <b>{routing.preset}</b>. User overrides always
              win over Auto.
            </p>
          </>
        ) : (
          <div className="empty">Routing unavailable.</div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Benchmark</h3>
        <button className="ghost" onClick={runBenchmark}>
          Run core benchmarks
        </button>
        {benchmark && <pre className="log" style={{ marginTop: 12 }}>{benchmark}</pre>}
      </div>
    </div>
  );
}
