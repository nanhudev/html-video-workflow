# API

One video pipeline, four entry points. All four construct the same
`CreateVideoRequest` and call the same `VideoRuntime.create_video()`. There is
no per-entry-point implementation, so a capability cannot exist in one place
and not another.

```
CLI  ─┐
SDK  ─┼──▶  CreateVideoRequest  ──▶  VideoRuntime.create_video()  ──▶  VideoResult
REST ─┤
MCP  ─┘
```

---

## 1. Python

```python
from html_video_workflow import create_video

result = create_video(
    "Why local AI matters",    # the prompt may be positional
    platform="youtube_16x9",   # or aspect="16:9" / width + height
    duration_sec=45,
    scenes=6,
    out_dir="out",             # a directory; result.video_path names the file
)
```

The prompt may be given positionally, as `prompt="..."`, or inside a
`CreateVideoRequest`. Passing both forms at once, passing more than one
positional argument, or naming a field that does not exist all raise
`TypeError` — the SDK never ignores an argument it does not understand.

| Returns | Meaning |
| --- | --- |
| `result.ok` | the only field a caller must check |
| `result.video_path` | absolute path to the MP4 (present when `ok`) |
| `result.duration_sec` | measured with ffprobe on the exported file |
| `result.template` / `.style` | what the planner chose |
| `result.reasons` | one string per planning decision |
| `result.warnings` | things the caller should know (trimmed narration, …) |
| `result.fallbacks` | every silent-degradation escape hatch, with a reason |
| `result.error` / `.error_code` | set when `ok` is false |

`create_video(...)` is synchronous. Pass `wait=False` to get a `job_id` and
poll with `VideoRuntime.job_result(job_id)`.

---

## 2. CLI

```bash
html-video generate "Why local AI matters"
html-video generate "..." --out out --platform youtube_shorts_9x16 --duration 30
html-video generate "..." --source https://example.com/article
html-video generate "..." --template data_story --style blueprint
html-video generate "..." --dry-run          # plan only
html-video generate "..." --no-wait --json   # job id, machine-readable
html-video generate "..." --width 320 --height 180   # fast smoke render
```

| Flag | Meaning |
| --- | --- |
| `--platform` | a preset id (`youtube_16x9`, `tiktok_9x16`, `xiaohongshu_3x4`, …) |
| `--aspect` | `16:9` `9:16` `1:1` `4:5` `3:4` |
| `--width` / `--height` | explicit pixels, override the preset |
| `--duration` | target seconds |
| `--scenes` | target scene count (clamped to the template's range) |
| `--template` / `--style` | force a choice; a forced mismatch is recorded in `reasons` |
| `--dry-run` | plan and build the IR, do not render |
| `--strict` | treat a QC failure as an error |
| `--json` | machine-readable result |

Exit codes follow `VideoErrorCode` (`invalid_request` → 2, …).

---

## 3. REST — `/v1`

Base path is versioned. `GET /health` and `GET /v1/...` do not require auth in
a local deployment.

### `POST /v1/videos`

Body is a `CreateVideoRequest`. Query `?wait=true|false` overrides the body's
`wait`.

```jsonc
{
  "prompt": "Why local AI matters",
  "platform": "youtube_16x9",
  "duration_sec": 45,
  "scenes": 6,
  "language": "zh-CN",
  "template": null,
  "style": null,
  "out_dir": null,
  "wait": true,
  "dry_run": false,
  "strict": false
}
```

`wait=true` (default) blocks and returns the finished `VideoResult`.
`wait=false` returns immediately with `job_id` and `status`.

### Other endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/videos` | list jobs |
| `GET` | `/v1/videos/{job_id}` | job status / result (404 when never issued) |
| `GET` | `/v1/videos/{job_id}/events` | progress events |
| `DELETE` | `/v1/videos/{job_id}` | cancel |
| `GET` | `/v1/templates` | every template manifest, verbatim |
| `GET` | `/v1/templates/{id}` | one manifest (404 when unknown) |
| `GET` | `/v1/styles` | style profiles |
| `GET` | `/v1/platforms` | platform presets |
| `GET` | `/v1/topics/suggest?prompt=…&count=3` | ranked topic angles |

### Status codes

| Code | Meaning | `VideoErrorCode` |
| --- | --- | --- |
| `200` | done (or a job handle when `wait=false`) | — |
| `400` | the request named a source that cannot be read | `no_source`, `source_unreadable` |
| `404` | the named thing does not exist | `no_template`, `job_not_found` |
| `409` | the job was cancelled | `cancelled` |
| `422` | the request cannot be validated (no intent, bad duration, …) | `invalid_request` |
| `500` | a stage failed mid-run | `planning_failed`, `render_failed`, `tts_failed`, `compose_failed`, `quality_failed`, `internal` |
| `503` | no provider can serve a required stage | `no_provider` |

A job id that was never issued is `404` with `job_not_found`, not `422`: the
caller did not ask badly, they asked for something that is not there. The same
rule applies to an unknown template, and to `/v1/videos/{id}/events`, where an
empty list would otherwise be indistinguishable from "this job has no events
yet".
| `503` | no provider can satisfy a stage |
| `500` | a stage failed |

Errors carry a structured body: `{"detail": {"code": ..., "message": ..., "detail": {}}}`.

---

## 4. MCP

`html-video-mcp` speaks JSON-RPC over stdio. Tools:

| Tool | Purpose |
| --- | --- |
| `create_video` | the same Runtime as every other entry point |
| `suggest_topics` | ranked angles for a domain |
| `list_templates` / `list_styles` | the catalogue |
| `get_job` | poll an async job |

```jsonc
{ "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": { "name": "create_video",
              "arguments": { "prompt": "Why local AI matters", "duration_sec": 30 } } }
```

The server is agent-neutral: nothing in it is specific to WorkBuddy, Codex,
Cursor or Claude Code.

---

## 5. `CreateVideoRequest`

Only one intent field is required — `prompt`, `topic`, `script` or `source`.
Everything else is a preference the planner honours when it can and records
when it cannot.

| Field | Type | Notes |
| --- | --- | --- |
| `prompt` | string | free-form ask |
| `topic` | string | short title |
| `script` | string | pre-written narration; skips script planning |
| `source` | `SourceInput` | `{kind, value, max_chars}`; `kind` is `auto` by default |
| `language` | string | default `zh-CN` |
| `platform` / `aspect` / `width` / `height` | | delivery shape |
| `duration_sec` | float | **a target**, 5–1200 |
| `scenes` | int | **a target**, clamped to the template's range |
| `template` / `style` | string | force a choice |
| `voice` | string | TTS voice |
| `captions` | bool | default `true` |
| `preset` | `auto`/`fast`/`balanced`/`high_quality`/`max_quality` | routing bias |
| `llm` / `tts` / `renderer` | string | provider locks, recorded in `reasons` |
| `out_dir` | string | where the MP4 goes |
| `wait` | bool | block, or return a job id |
| `dry_run` | bool | plan only |
| `strict` | bool | QC failure becomes an error |

Whitespace-only intent is rejected: `"   "` carries no intent and would
otherwise produce a video about nothing.

### Source kinds

| `kind` | `value` is |
| --- | --- |
| `auto` | inferred: GitHub URL, web URL, existing file path, else text |
| `text` | literal prose |
| `markdown` | markdown **content**, or a path when one exists |
| `file` | a local path (raises when absent) |
| `webpage` / `url` | an http(s) page |
| `github` | a repository URL (reads its README) |

Plain dicts are accepted at the public boundary and normalised into
`SourceInput`.

---

## 6. Duration contract

`duration_sec` is a **target**, honoured within ±10% where the material allows.

- **Too long** → narration is trimmed. Timing follows the words; rescaling
  scene clocks while the words stay long is how a "20 second" video used to
  come out 32 seconds. A `warning` is recorded.
- **Too short** → trimming cannot add time, and padding a video with held
  frames is just dead air. The shortfall is reported in `warnings` and the
  real number is returned.

Speech length is measured by one canonical estimator
(`utils.audio.estimate_speech_seconds`: 5.2 CJK chars/s, ~13 latin chars/s).
The planner, the storyboard and the audio stage all use it — never a private
copy of the number.
