/** Typed access to the Runtime API. The Studio never talks to Python directly. */

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail.slice(0, 400));
  }
  return (await response.json()) as T;
}

// ------------------------------------------------------------------- types
export interface SystemInfo {
  version: string;
  home: string;
  outputs: string;
  settings: Record<string, unknown>;
  secrets: Record<string, string>;
}

export interface ToolInfo {
  name: string;
  available: boolean;
  path: string | null;
  version: string | null;
}

export interface HardwareProfile {
  os: string;
  os_version: string;
  arch: string;
  cpu_model: string | null;
  cpu_logical_cores: number | null;
  ram_total_mb: number | null;
  ram_free_mb: number | null;
  gpus: { vendor: string; model: string | null; vram_mb: number | null; driver_version: string | null }[];
  accelerators: Record<string, boolean | null>;
  tooling: Record<string, ToolInfo>;
  disk_free_mb: number | null;
  probed_at: string | null;
  /** Derived server-side so consumers never re-sum the GPU list. */
  vram_total_mb: number;
  has_gpu: boolean;
  primary_gpu: string | null;
}

export interface Capability {
  id: string;
  type: string;
  available: boolean;
  state: string;
  local: boolean;
  languages: string[];
  voices: { id: string; name: string; language: string | null }[];
  quality_score: number;
  speed_score: number;
  naturalness_score: number;
  reason: string | null;
  details: Record<string, unknown>;
}

export interface RoutingInfo {
  preset: string;
  hardware: Record<string, unknown>;
  selection: Record<string, string | null>;
  reasons: Record<string, { stage: string; preset: string; selected: string | null; candidates: Candidate[] }>;
  fallbacks: Record<string, string[]>;
}

export interface Candidate {
  id: string;
  score: number;
  chosen: boolean;
  reason: string[];
}

export interface ProjectSummary {
  id: string;
  title: string;
  language: string;
  scene_count: number;
  updated_at: string;
  path: string;
}

export interface JobStep {
  id: string;
  name: string;
  status: string;
  provider: string | null;
  progress: number;
  error: string | null;
  metrics: Record<string, unknown>;
  artifacts: { name: string; path: string; kind: string }[];
}

export interface JobView {
  id: string;
  project_id: string;
  status: string;
  progress: number;
  preset: string;
  plan: { preset: string; llm: string | null; tts: string | null; renderer: string | null; reasons: Record<string, string[]> };
  tasks: { stage: string; name: string; status: string; progress: number; steps: JobStep[] }[];
  outputs: Record<string, string>;
  errors: { type: string; message: string }[];
  fallbacks: { stage: string; from: string; to: string; reason: string }[];
  quality: { passed: boolean; failed: string[]; warned: string[]; checks: { name: string; status: string; detail: string }[] } | null;
}

// -------------------------------------------------------------------- calls
export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  system: () => request<SystemInfo>("/system"),
  hardware: (refresh = false) => request<HardwareProfile>(`/hardware?refresh=${refresh}`),
  providers: (type?: string) =>
    request<Capability[]>(type ? `/providers?provider_type=${type}` : "/providers"),
  routing: (preset = "auto", language = "zh-CN") =>
    request<RoutingInfo>(`/routing?preset=${preset}&language=${language}`),
  projects: () => request<ProjectSummary[]>("/projects"),
  createProject: (payload: {
    prompt?: string;
    script?: string;
    language?: string;
    preset?: string;
    llm?: string;
  }) =>
    request<{ id: string; scenes: number; project: unknown }>("/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generate: (projectId: string, preset = "auto", overrides: Record<string, string> = {}) =>
    request<{ job_id: string; status: string }>(`/projects/${projectId}/generate`, {
      method: "POST",
      body: JSON.stringify({ preset, overrides, background: true }),
    }),
  job: (jobId: string) => request<JobView>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  benchmarks: () => request<Record<string, unknown>>("/benchmarks"),
};
