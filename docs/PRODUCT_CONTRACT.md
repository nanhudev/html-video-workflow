# Product Contract — one prompt in, one MP4 out

This document fixes what "one click" means. Every entry point is measured
against it, and a change that breaks any clause here is a breaking change.

## 1. The promise

> **One user action → the full pipeline runs unattended → a real MP4 exists on disk,
> verified by ffprobe, or the user is told exactly why not.**

"One user action" is one of:

| Entry point | The one action |
| --- | --- |
| CLI | `html-video generate "explain vector databases"` |
| Python | `create_video(prompt="explain vector databases")` |
| REST | `POST /v1/videos {"prompt": "..."}` |
| MCP / Agent Skill | `create_video` tool call |
| Studio | type a prompt, press **Generate** |

A second command to "render", "compose" or "export" means the contract is broken.

## 2. The single source of truth

```
GUI ─┐
CLI ─┤
API ─┼─▶ CreateVideoRequest ─▶ VideoRuntime.create_video(req) ─▶ VideoResult
MCP ─┤        (one model)            (one implementation)         (one shape)
SDK ─┘
```

- Entry points do **parsing, presentation and transport**. Nothing else.
- No entry point may call a provider directly, own a fallback decision, or
  compute an output path. Those live in the Runtime and the planners.
- If a capability is reachable from one entry point only, that is defect
  `E-001`, not a feature.

## 3. The request

`CreateVideoRequest` (`src/html_video_workflow/core/request.py`). Only one
intent field is required — `prompt`, `topic`, `script` or `source`. Everything
else is a *preference*:

- Honoured when possible.
- Recorded in `VideoResult.reasons` when it changes the plan.
- Recorded in `VideoResult.fallbacks` when it could not be honoured.

Overrides (`llm` / `tts` / `renderer` / `template` / `style`) are legitimate but
never silent — a forced `renderer` appears in the plan's reasons.

## 4. The result

`VideoResult` — the same object every entry point receives. The CLI prints it,
the API serialises it, the SDK returns it, MCP returns `to_dict()`.

- `ok` is the only field a caller must check.
- `video_path` is non-null **only** when ffprobe confirms a real file.
- `fallbacks` is never silently empty when something degraded.
- `qc` carries the quality verdict; with `strict=True` a QC failure makes
  `ok=False`.

## 5. No fake completion

These are forbidden and are treated as severity-1 defects:

- Reporting success before the MP4 exists.
- Returning a path to a file of size 0, or one ffprobe cannot open.
- Claiming a provider is ready without a probe (see `doctor`: `--` / `??`).
- Swallowing a fallback instead of recording it in `job.fallbacks`.
- Returning `ok=True` with `video_path=None` because "rendering was skipped".

## 6. Determinism and identity

- The same `CreateVideoRequest` on the same machine produces the same plan.
- Every run gets a `project_id` and a `job_id`; artifacts live under
  `$HVW_HOME/projects/<project_id>/`.
- Re-running does not collide: ids are generated, never derived from the title.

## 7. Layers that must not leak

IR V2 layers stay renderer-neutral: `{type, role, content, layout, motion}`.
No `remotionComponent`, no `cssClass`. A template manifest may *hint* at a
layout primitive; it may never name a renderer.

## 8. Exit codes (CLI) and status codes (REST)

Both come from one table — `core/errors.py` → `VideoErrorCode`. The CLI never
invents an exit status and the API never invents a status code.
