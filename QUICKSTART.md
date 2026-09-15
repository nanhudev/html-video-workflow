# Quickstart

One prompt in. A complete MP4 out.

## Install

```bash
python -m venv .venv && .venv/bin/pip install html-video-workflow
.venv/bin/html-video doctor          # see what this machine can actually do
```

Requirements: Python ≥ 3.11 and FFmpeg on `PATH`. Everything else is optional —
the runtime probes for providers and falls back with a recorded reason instead
of failing.

## Your first video

```bash
html-video generate "Why local AI matters"
```

That runs the whole pipeline: source → topic → template → script → storyboard →
render → voice → compose → QC. When it finishes you get the path, the measured
duration, and the decisions it made.

## The same thing from Python

```python
from html_video_workflow import create_video

result = create_video("Why local AI matters", out_dir="out")
print(result.video_path, result.duration_sec)
```

The first argument is the prompt. `create_video(prompt="...")` and
`create_video(CreateVideoRequest(...))` mean the same thing; a misspelled field
is an error, never a silently ignored one.

## Choose a shape

```bash
html-video generate "..." --platform youtube_shorts_9x16 --duration 30
html-video generate "..." --aspect 1:1
html-video generate "..." --width 1920 --height 1080
html-video generate "..." --scenes 6
```

`--duration` and `--scenes` are **targets**, clamped to what the template
supports. When the request cannot be met you get a warning, not a silent
substitution.

## Ground it in real material

```bash
html-video generate "..." --source https://example.com/article
html-video generate "..." --source https://github.com/nanhudev/html-video-workflow
html-video generate "..." --source ./notes.md
```

Web and repo sources are read at request time; the text is truncated loudly
(`warning`) rather than silently.

## See what it would do, before it does it

```bash
html-video generate "..." --dry-run --json
```

## Pick the look

```bash
html-video templates          # the catalogue, with what each is for
html-video styles
html-video generate "..." --template data_story --style blueprint
```

A template is the *structure of the argument*; a style is the *skin*. They are
independent, and forcing a mismatched pair is allowed but recorded in
`result.reasons`.

## Serve it

```bash
html-video studio             # the GUI on http://127.0.0.1:8787
html-video serve              # the same app, described as an API
```

Both serve the prebuilt Studio and the REST API from one process — no Node
required. `html-video studio` says so plainly if the frontend was never built.

```http
POST /v1/videos  {"prompt": "Why local AI matters", "duration_sec": 45}
```

```bash
html-video-mcp                # JSON-RPC over stdio, for agents
```

## When something looks wrong

```bash
html-video doctor             # per-provider truth: OK / ?? / --
```

`??` means installed but unusable (no model, no key). `--` means not installed.
Neither is a bug — the runtime reports what it actually probed.

Every result carries `reasons`, `warnings` and `fallbacks`. If a video came out
shorter than asked, or in a different template, the explanation is in there.
