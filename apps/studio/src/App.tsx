import { useEffect, useState } from "react";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import Generate from "./pages/Generate";
import Hardware from "./pages/Hardware";
import Providers from "./pages/Providers";
import Projects from "./pages/Projects";
import NewProject from "./pages/NewProject";
import SettingsPage from "./pages/Settings";

type Route = "home" | "generate" | "projects" | "new" | "providers" | "hardware" | "settings";

const NAV: { id: Route; label: string; badge?: string }[] = [
  { id: "home", label: "Home" },
  { id: "generate", label: "Generate" },
  { id: "new", label: "New Project" },
  { id: "projects", label: "Projects" },
  { id: "providers", label: "Providers" },
  { id: "hardware", label: "Hardware" },
  { id: "settings", label: "Settings" },
];

function routeFromHash(): Route {
  const raw = window.location.hash.replace("#", "") as Route;
  return NAV.some((item) => item.id === raw) ? raw : "home";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash());
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    api
      .health()
      .then(() => setOnline(true))
      .catch(() => setOnline(false));
  }, []);

  const go = (next: Route) => {
    window.location.hash = next;
    setRoute(next);
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          Video Studio
          <small>HTML VIDEO WORKFLOW</small>
        </div>
        {NAV.map((item) => (
          <button
            key={item.id}
            className={`nav ${route === item.id ? "active" : ""}`}
            onClick={() => go(item.id)}
          >
            <span>{item.label}</span>
            {item.badge ? <span className="badge">{item.badge}</span> : null}
          </button>
        ))}
        <div className="sidebar-footer">
          Runtime API{" "}
          <span className={`pill ${online ? "ok" : "fail"}`}>
            {online === null ? "…" : online ? "ONLINE" : "OFFLINE"}
          </span>
          <div style={{ marginTop: 8 }}>
            {online === false ? "Start: html-video serve" : "Local-first, not local-only"}
          </div>
        </div>
      </aside>
      <main className="main">
        {route === "home" && <Dashboard onNavigate={go} />}
        {route === "generate" && <Generate />}
        {route === "new" && <NewProject onCreated={() => go("projects")} />}
        {route === "projects" && <Projects />}
        {route === "providers" && <Providers />}
        {route === "hardware" && <Hardware />}
        {route === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
