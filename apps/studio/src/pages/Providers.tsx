import { useEffect, useState } from "react";
import { api, Capability } from "../api";

const STATE_LABEL: Record<string, { text: string; cls: string }> = {
  ready: { text: "READY", cls: "ok" },
  not_installed: { text: "NOT INSTALLED", cls: "warn" },
  unavailable: { text: "UNAVAILABLE", cls: "fail" },
  missing_credentials: { text: "NO CREDENTIALS", cls: "warn" },
  error: { text: "ERROR", cls: "fail" },
};

export default function Providers() {
  const [rows, setRows] = useState<Capability[]>([]);
  const [type, setType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api
      .providers(type || undefined)
      .then(setRows)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [type]);

  const types = Array.from(new Set(rows.map((row) => row.type))).sort();

  return (
    <div>
      <h1 className="page-title">Providers</h1>
      <p className="page-sub">
        A provider reports <b>ready</b> only after a real probe. Anything not installed is
        shown as not installed — never as available.
      </p>
      {error && <div className="error">{error}</div>}

      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 16 }}>
        <div className="field" style={{ maxWidth: 220, marginBottom: 0 }}>
          <label>Filter by type</label>
          <select value={type} onChange={(event) => setType(event.target.value)}>
            <option value="">all</option>
            {types.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <button className="ghost" onClick={load} disabled={loading}>
          {loading ? "Probing…" : "Re-probe all"}
        </button>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>State</th>
              <th>Type</th>
              <th>Provider</th>
              <th>Local</th>
              <th>Q / S / N</th>
              <th>Languages</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const state = STATE_LABEL[row.state] ?? { text: row.state, cls: "neutral" };
              return (
                <tr key={`${row.type}-${row.id}`}>
                  <td>
                    <span className={`pill ${state.cls}`}>{state.text}</span>
                  </td>
                  <td>{row.type}</td>
                  <td style={{ fontFamily: "var(--mono)" }}>{row.id}</td>
                  <td>{row.local ? "local" : "api"}</td>
                  <td>
                    {row.quality_score}/{row.speed_score}/{row.naturalness_score}
                  </td>
                  <td>{row.languages.join(", ") || "—"}</td>
                  <td style={{ color: "var(--muted)" }}>
                    {row.reason ?? "—"}
                    {row.voices.length > 0 && (
                      <div style={{ fontSize: 11, marginTop: 4 }}>
                        voices: {row.voices.map((v) => v.name).join(", ").slice(0, 90)}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && !loading && <div className="empty">No providers registered.</div>}
      </div>
    </div>
  );
}
