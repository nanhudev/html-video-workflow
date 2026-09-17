# ARCHITECTURE

> This project is not an AI slideshow generator.
>
> It is a local-first agentic video production runtime.
>
> The agent decides what should be shown.
>
> The IR describes what the video means.
>
> Providers decide how capabilities are executed.
>
> The runtime chooses the best available pipeline.
>
> The quality system decides whether the output is acceptable.
>
> The Studio makes the entire process observable and editable.

Corollaries:

> Local-first, not local-only.
>
> Plugin-first, not dependency-heavy.
>
> Deterministic when possible, generative when useful.
>
> Quality over feature count.
>
> Task-fit over model size.
>
> Reduce AI feel through editorial decisions, not random decoration.

---

## 1. Big picture

```
                     ┌──────────────────────────────┐
   GUI  CLI  REST  MCP│        Local Studio          │
                     │   React + TypeScript + Vite   │
                     └───────────────┬──────────────┘
                                     │  HTTP (REST + SSE)
                     ┌───────────────▼──────────────┐
                     │        Runtime API            │
                     │   FastAPI (thin, no logic)    │
                     └───────────────┬──────────────┘
                                     │
                     ┌───────────────▼──────────────┐
                     │      Workflow Engine          │
                     │  Job / Task / Step / Artifact │
                     │  Cache / Retry / Resume / SSE │
                     └───────────────┬──────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
  ┌──────────────┐           ┌──────────────┐            ┌──────────────┐
  │ PipelinePlan │           │  Provider    │            │  Quality     │
  │ (Planner +   │  selects  │  Registry    │  executes  │  Engine      │
  │  Router)     │──────────▶│  (capability │──────────▶ │  (media +    │
  └──────┬───────┘           │   aware)     │            │   editorial) │
         │                   └──────┬───────┘            └──────────────┘
         │                          │
         ▼                          ▼
  ┌──────────────┐   ┌──────────────────────────────────────────────────┐
  │ Hardware     │   │ llm · tts · asr · renderer · avatar · image ·     │
  │ Profiler +   │   │ video · music · asset · subtitle · storage ·      │
  │ Benchmark    │   │ agent — local process / HTTP / subprocess / API   │
  └──────────────┘   └──────────────────────────────────────────────────┘
                                     │
                              ┌──────▼───────┐
                              │ FFmpegService│ → MP4 / Shorts / Reels
                              └──────────────┘
```

## 2. Layer responsibilities

| Layer | Owns | Must NOT |
|---|---|---|
| **Studio** (React/TS) | rendering state, editing, visualising | decide providers, know GPU rules |
| **API** (FastAPI) | transport, validation, SSE | contain pipeline logic |
| **Engine** | job lifecycle, artifacts, cache, events | know what a "scene" means |
| **Pipeline** | stage sequencing, plan/fallback, routing | import torch / call providers directly |
| **Providers** | one capability each, self-described | import each other |
| **IR** (`project/`) | the meaning of a video | reference a renderer component |
| **Hardware** | truth about the machine | recommend without evidence |
| **Quality** | accept/reject decisions | mutate the project silently |

## 3. The production chain

```
Brief (prompt / script / URL / markdown / local assets)
   │  understand
   ▼
Script  ──▶ ScriptCritic ──▶ Humanization pass
   │
   ▼
Story beats (Beat: hook / reveal / evidence / payoff …)
   │
   ▼
Storyboard (Scene ▸ Shot ▸ Layer) + Visual strategy
   │
   ▼
Scene IR  ──▶ AssetPlan (typography / SVG / chart / screenshot / stock / generated / avatar)
   │
   ├──▶ Narration IR ──▶ ProsodyPlanner ──▶ TTS Provider ──▶ AudioProcessor
   ├──▶ Renderer Provider (HTML / Remotion / Motion Canvas)
   ├──▶ Caption IR (SRT / ASS / WebVTT, burn-in or sidecar)
   └──▶ Music / SFX + BGM ducking
   │
   ▼
FFmpegService compose ──▶ QualityEngine ──▶ Output (MP4 + manifest)
```

Every arrow is a **Step** in the Engine: it produces an Artifact, is cached by
input hash, and can be retried, resumed or re-run in isolation.

## 4. IR hierarchy

```
Project
 └ Sequence
    └ Scene            (intent, duration, narration, visual_strategy)
       └ Shot          (start, duration, camera, layers, caption)
          └ Layer      (text | image | video | svg | html | chart | shape | avatar | effect)
```

The IR is **renderer neutral**. A layer is
`{"type": "text", "role": "headline", "content": "..."}` — never
`{"remotionComponent": "..."}`. The renderer decides how to realise it.

See [VIDEO_IR_V2.md](VIDEO_IR_V2.md).

## 5. Providers

Every Provider is a class that:

1. declares a `ProviderSpec` (id, type, local?, languages, streaming, gpu, vram,
   quality/speed/naturalness scores, install state),
2. answers `probe()` honestly — never "Ready" without a real check,
3. answers `capabilities()` with concrete data,
4. executes one narrow job.

See [PROVIDER_SPEC.md](PROVIDER_SPEC.md).

Provider **types**: `llm`, `tts`, `asr`, `renderer`, `avatar`, `image`, `video`,
`music`, `asset`, `subtitle`, `storage`, `agent`.

## 6. Hardware & routing

`HardwareProfiler` probes OS/arch/CPU/RAM/GPU/VRAM/accelerators/FFmpeg/Chromium
with **no hardcoded machine facts**. `BenchmarkService` measures real throughput
and stores it in `~/.html-video-workflow/benchmarks.json`.

Routing combines `hardware + benchmark + project requirement` and returns an
**explained** decision:

```json
{ "selected": "sapi", "reason": ["supports zh-CN", "available locally", "no GPU required"] }
```

Presets exposed to users: `Auto`, `Fast`, `Balanced`, `High Quality`, `Max
Quality`, `Custom`. User overrides (locked providers) always win.

See [HARDWARE_ROUTING.md](HARDWARE_ROUTING.md).

## 7. Runtime model

```
Job ──▶ Task ──▶ Step ──▶ Artifact
status: queued | planning | running | paused | failed | completed | cancelled
```

Per project on disk:

```
projects/<id>/
  project.json          # Video IR (V2) — the portable source of truth
  runtime/job.json      # job + task/step graph + status
  runtime/artifacts.json
  runtime/events.jsonl  # append-only observability stream
  runtime/providers.json
  runtime/quality.json
```

SQLite holds **indexes only** (projects, jobs, provider state, benchmark,
settings). It is never the sole source of truth — deleting it must not lose a
project.

## 8. Entry points

Four equal surfaces, all talking to the same Runtime:

| Surface | Location |
|---|---|
| GUI | `apps/studio` |
| CLI | `html-video …` (`src/…/cli`) |
| REST | `src/…/api` |
| MCP | `integrations/mcp` (skeleton in Foundation) |

The Runtime **must run with no frontend** — that is what makes agent access
possible.

## 9. Configuration layers

```
runtime override  >  project  >  user  >  system  >  default
```

Secrets live in `.env` / environment only. They are never written into
`project.json`, logs, git, or browser storage, and are masked (`sk-****7a3`) in
every API response.

## 10. Error model

Typed errors: `ProviderUnavailable`, `ProviderNotInstalled`, `ProviderTimeout`,
`OutOfMemory`, `RenderFailed`, `InvalidProject`, `MissingAsset`,
`UnsupportedCapability`. Each carries a human message plus a suggested fallback.
Fallbacks are **always recorded in the manifest** — quality is never silently
degraded.

## 11. Repository layout

```
apps/studio/                 React + TypeScript + Vite Studio
src/html_video_workflow/
    api/      FastAPI app + routers
    runtime/  engine, job model, events, cache
    pipeline/ planner, router (auto routing), stages
    project/  IR V2 models, migration, store
    providers/base|registry|capabilities + llm/ tts/ renderer/ avatar/ media/
    hardware/ profiler, benchmark
    ffmpeg/   service
    quality/  media + editorial checks
    config/   settings, paths
    legacy/   adapter to scripts/workflow.py
    cli/      `html-video` entry point
    utils/    logging
integrations/mcp/            MCP adapter (skeleton)
schemas/                     JSON Schemas for IR V2
templates/                   renderer themes (legacy 10 + new)
references/                  design principles, provider notes
docs/architecture|research|providers|development
tests/                       unit / integration / smoke
legacy/                      frozen copy reference (scripts/ stays authoritative)
examples/                    sample projects
```

`scripts/workflow.py` stays untouched — see
[docs/architecture/legacy-audit.md](docs/architecture/legacy-audit.md).
