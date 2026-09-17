# Development Guide

Everything needed to go from a fresh clone to a rendered video, plus the
conventions that keep the codebase coherent.

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | ≥ 3.11 | dataclasses, `X \| Y` unions, `tomllib` |
| Node.js | ≥ 20 | Studio SPA only; the Python side has no Node dependency |
| FFmpeg | any recent build | compose, loudness normalisation, all QC probes |
| A Chromium browser | Edge / Chrome / Chromium | `legacy_html` renderer |

`html-video doctor` checks all four and tells you exactly what is missing. It
never claims something is ready without probing it.

## 2. Environment layout

Heavy state deliberately lives outside the repository. The default home is
`D:\html-video-workflow` (or `E:`) when that drive exists, otherwise
`~/.html-video-workflow`.

```
<html>/
  cache/         content-addressed render/TTS cache + index.json
  models/        model weights (empty until you pull one)
  projects/      <project_id>/project.json + runtime/{job,artifacts,providers}.json
  outputs/       final .mp4 / .jpg deliverables
  work/          <project_id>/<job_id>/{scenes,audio,segments,captions}
  logs/          <job_id>.log
  benchmarks.json  hardware.json  settings.json
```

Override with `HVW_HOME`. These are all accepted and equivalent:

```bash
export HVW_HOME=/d/html-video-workflow     # Git Bash alias
export HVW_HOME='D:\html-video-workflow'   # Windows
export HVW_HOME=D:/html-video-workflow     # forward slashes
```

A **relative** value raises an error on purpose. It used to silently create a
directory literally named `\d\html-video-workflow` inside the repo.

## 3. Setup

```bash
# Python (keep the venv on the data drive too)
python -m venv D:/html-video-workflow/venv
D:/html-video-workflow/venv/Scripts/pip install -e ".[dev]"     # or: [api,dev]

# Studio
cd apps/studio && npm install
```

## 4. Running

```bash
html-video doctor                       # hardware + toolchain + provider honesty
html-video providers                    # probe every provider, show real state
html-video validate assets/demo-us-study-2026.json
html-video create "topic" --preset fast --render
html-video render <project_id> --preset balanced
html-video status <job_id>
html-video gallery --project <path>     # legacy template gallery
html-video serve                        # REST API on 127.0.0.1:8787
```

Studio dev server (proxies the API, so start `serve` first):

```bash
cd apps/studio && npm run dev            # http://localhost:5173
```

## 5. Testing

```bash
pytest tests -q                          # 74 tests, no downloads, no paid APIs
pytest tests -m integration              # opt-in: touches real ffmpeg/browser
cd apps/studio && npm run typecheck && npm run build
```

Rules the suite depends on:

- **Never** download a model or call a paid API. Use mock providers.
- `isolated_home` points `HVW_HOME` at a tmp dir and clears the `hv_home` cache,
  so tests never touch real user data.
- `clean_env` strips `*API_KEY`, `OPENAI_BASE_URL` and `HVW_LLM_BASE_URL`, so
  provider state is deterministic regardless of the developer's shell.

## 6. Code conventions

**Layers.** `config` → `hardware` → `project` → `providers` → `pipeline` →
`runtime` → `api`/`cli`. A lower layer must never import a higher one.

**Provider isolation.** No heavy import (torch, diffusers, engine SDKs) at module
import time. Import inside `execute()`/`synthesize()`. Discovery imports every
provider, so a slow import becomes a slow boot.

**Honest state.** Never return `available=True`, `READY` or `passed` from a
static value. It must come from a probe that actually ran.

**Errors.** Use the typed errors in `providers/base.py`
(`ProviderUnavailable`, `ProviderNotInstalled`, `ProviderTimeout`, `OutOfMemory`,
`RenderFailed`, `InvalidProject`, `MissingAsset`, `UnsupportedCapability`) —
the runtime matches on them to decide whether to fall back.

**No silent degradation.** Every provider substitution appends to
`job.fallbacks` with `{stage, from, to, reason}`.

**Comments explain why.** The interesting fact is usually the failure that
motivated the code, or the constraint that makes the obvious approach wrong.

## 7. Adding a provider

1. Subclass the right base (`TTSProvider`, `RendererProvider`, …) in
   `src/html_video_workflow/providers/<type>/<name>.py`.
2. Decorate the class with `@register`.
3. Implement `spec` honestly — `quality_score` and `startup_cost` describe the
   *best case*, and ranking uses them only as a prior.
4. Implement `probe()` to actually check binaries, credentials and models.
   Return `NOT_INSTALLED` / `MISSING_CREDENTIALS` rather than guessing.
5. Add the module to `BUILTIN_MODULES` in `providers/registry.py`.
6. Add it to the relevant chain in `pipeline/router.py:FALLBACKS` if it can serve
   as a fallback.
7. Add a test asserting its probe is honest when its dependency is absent.
8. Run `html-video providers` and confirm it does not appear ready.

When a module fails to import, `registry.load_failures()` names it. Check that
first if a provider silently does not show up.

## 8. Working on the renderer

The renderer reads **only** the IR. If you need a new visual, add:

- a `motion.semantic` value, or
- a layer `role`,

and interpret it in `providers/renderer/document.py`. Do not add a CSS class that
the IR refers to — that couples the data to one renderer, which
`test_document_is_renderer_neutral` will fail on.

Typography comes from `ROLE_STYLE`; themes come from
`providers/renderer/themes.py`. The ten original themes are byte-frozen: editing
them changes existing users' output.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A provider is missing from `providers` | Its module failed to import | Check `registry.load_failures()`; the error is logged at error level |
| `renderer` falls back to `mock_renderer` | No Edge/Chrome/Chromium found | Install one, or check `doctor` |
| `llm` uses `mock_llm` | No API key configured | Set `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`, or accept mock output |
| `HVW_HOME ... is not an absolute path` | Relative value in the env | Use a drive-qualified path |
| Cache hit rate 0% on repeat runs | Provider config or content changed | Expected; the key includes content + provider + config hash |
| Studio shows nothing | API not running | `html-video serve` first; Vite proxies to port 8787 |
