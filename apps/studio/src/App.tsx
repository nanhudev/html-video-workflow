import { useEffect, useState } from "react";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import Generate from "./pages/Generate";
import Hardware from "./pages/Hardware";
import Providers from "./pages/Providers";
import Projects from "./pages/Projects";
import NewProject from "./pages/NewProject";
import SettingsPage from "./pages/Settings";
import Works from "./pages/Works";
import Wizard from "./wizard/Wizard";

type Route =
  | "create"
  | "works"
  | "home"
  | "generate"
  | "projects"
  | "new"
  | "providers"
  | "hardware"
  | "settings";

const NAV: { id: Route; label: string; advanced?: boolean }[] = [
  { id: "create", label: "开始创作" },
  { id: "works", label: "我的作品" },
  { id: "projects", label: "项目清单", advanced: true },
  { id: "generate", label: "单页生成", advanced: true },
  { id: "new", label: "手写脚本", advanced: true },
  { id: "providers", label: "Provider", advanced: true },
  { id: "hardware", label: "硬件", advanced: true },
  { id: "home", label: "总览", advanced: true },
  { id: "settings", label: "设置", advanced: true },
];

function routeFromHash(): Route {
  // `#create/3` is a route plus a position within it. Splitting here rather
  // than in the wizard keeps one place that knows the URL is `route[/arg]`.
  const raw = window.location.hash.replace("#", "").split("/")[0] as Route;
  return NAV.some((item) => item.id === raw) ? raw : "create";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash());
  const [online, setOnline] = useState<boolean | null>(null);
  const [works, setWorks] = useState<number | null>(null);

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

  const primary = NAV.filter((item) => !item.advanced);
  const advanced = NAV.filter((item) => item.advanced);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          视频工作台
          <small>HTML VIDEO WORKFLOW</small>
        </div>
        {primary.map((item) => (
          <button
            key={item.id}
            className={`nav ${route === item.id ? "active" : ""}`}
            onClick={() => go(item.id)}
          >
            <span>{item.label}</span>
            {item.id === "works" && works ? (
              <span className="badge">{works}</span>
            ) : null}
          </button>
        ))}
        <div className="wz-rail-advanced" style={{ marginTop: 16, paddingTop: 12, borderTop: "1px dashed var(--border)", fontSize: 11, color: "var(--muted)", letterSpacing: "0.04em" }}>
          高级（给开发者）
        </div>
        {advanced.map((item) => (
          <button
            key={item.id}
            className={`nav ${route === item.id ? "active" : ""}`}
            onClick={() => go(item.id)}
          >
            <span>{item.label}</span>
          </button>
        ))}
        <div className="sidebar-footer">
          Runtime API{" "}
          <span className={`pill ${online ? "ok" : "fail"}`}>
            {online === null ? "…" : online ? "ONLINE" : "OFFLINE"}
          </span>
          <div style={{ marginTop: 8 }}>
            {online === false ? "本机服务已断开，请重启程序" : "全部在本机运行"}
          </div>
        </div>
      </aside>
      <main className={`main ${route === "create" ? "bleed" : ""}`}>
        {route === "create" ? <Wizard onWorksLoaded={setWorks} /> : null}
        {route === "works" ? <Works onCreate={() => go("create")} /> : null}
        {route === "home" && <Dashboard onNavigate={(next) => go(next as Route)} />}
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
