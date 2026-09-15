import { useEffect, useState } from "react";
import { api, SystemInfo } from "../api";

export default function Settings() {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .system()
      .then(setSystem)
      .catch((err: Error) => setError(err.message));
  }, []);

  const settings = system?.settings as Record<string, Record<string, unknown>> | undefined;

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">
        Config precedence: runtime override &gt; project &gt; user &gt; system &gt; default.
      </p>
      {error && <div className="error">{error}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h3>Secrets detected</h3>
          {system && Object.keys(system.secrets).length > 0 ? (
            <table>
              <tbody>
                {Object.entries(system.secrets).map(([key, value]) => (
                  <tr key={key}>
                    <td>{key}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">
              No API keys configured. Keys live in <code>.env</code> or environment only —
              never in project files, logs or the browser.
            </div>
          )}
        </div>

        <div className="card">
          <h3>Active configuration</h3>
          {settings ? (
            Object.entries(settings).map(([section, values]) => (
              <div key={section} style={{ marginBottom: 14 }}>
                <b style={{ fontSize: 13 }}>{section}</b>
                <table>
                  <tbody>
                    {Object.entries(values as Record<string, unknown>).map(([key, value]) => (
                      <tr key={key}>
                        <td>{key}</td>
                        <td style={{ fontFamily: "var(--mono)" }}>
                          {typeof value === "object" ? JSON.stringify(value) : String(value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
          ) : (
            <div className="empty">Loading…</div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Storage layout</h3>
        <dl className="kv">
          <dt>Home</dt>
          <dd>{system?.home ?? "—"}</dd>
          <dt>Outputs</dt>
          <dd>{system?.outputs ?? "—"}</dd>
          <dt>Version</dt>
          <dd>{system?.version ?? "—"}</dd>
        </dl>
        <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 10 }}>
          Override the home directory with the <code>HVW_HOME</code> environment variable.
          Keep models and caches off the system drive.
        </p>
      </div>
    </div>
  );
}
