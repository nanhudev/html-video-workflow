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
// ------------------------------------------------------------- v1 (product)
/** The product surface. Same shape the CLI and SDK receive. */
export interface VideoResult {
  ok: boolean;
  job_id: string | null;
  project_id: string | null;
  video_path: string | null;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  scenes: number;
  template: string | null;
  style: string | null;
  title: string | null;
  providers: Record<string, string>;
  fallbacks: Record<string, string>[];
  warnings: string[];
  reasons: string[];
  qc: { passed: boolean; failed: string[]; warned: string[] } | null;
  error: string | null;
  error_code: string | null;
  elapsed_sec: number | null;
  status?: string | null;
  progress?: number | null;
}

export interface TemplateManifest {
  id: string;
  name: string;
  description: string;
  best_for: string[];
  not_for: string[];
  aspects: string[];
  scene_count: { min: number; max: number; recommended: number };
  beats: string[];
  density: string;
  default_style: string;
  compatible_styles: string[];
  requires: string[];
}

export interface StyleProfile {
  id: string;
  name: string;
  description: string;
  palette: Record<string, string>;
  motion_bias: string;
  tags: string[];
}

export interface PlatformPreset {
  id: string;
  label: string;
  aspect: string;
  width: number;
  height: number;
  safe_bottom: number;
  max_duration_sec: number | null;
}

export interface TopicSuggestion {
  title: string;
  angle: string;
  rationale: string;
  video_type: string;
  score: number;
  source: string;
}

export interface CreateVideoBody {
  prompt?: string;
  topic?: string;
  source?: { kind?: string; value: string };
  script?: string;
  title?: string;
  language?: string;
  platform?: string;
  aspect?: string;
  duration_sec?: number;
  scenes?: number;
  template?: string;
  style?: string;
  voice?: string;
  captions?: boolean;
  preset?: string;
  wait?: boolean;
  dry_run?: boolean;
  strict?: boolean;
  created_by?: string;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  // ---- v1: the one-click product API
  createVideo: (body: CreateVideoBody) =>
    request<VideoResult>("/v1/videos", { method: "POST", body: JSON.stringify(body) }),
  video: (jobId: string) => request<VideoResult>(`/v1/videos/${jobId}`),
  templates: () => request<TemplateManifest[]>("/v1/templates"),
  styles: () => request<StyleProfile[]>("/v1/styles"),
  platforms: () => request<PlatformPreset[]>("/v1/platforms"),
  suggestTopics: (prompt: string, count = 5) =>
    request<TopicSuggestion[]>(
      `/v1/topics/suggest?prompt=${encodeURIComponent(prompt)}&count=${count}`,
    ),

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
