# Legacy Audit — html-video-workflow (pre-Next)

Audit date: 2026-09-15
Auditor: WorkBuddy (Foundation handover)
Repository: https://github.com/nanhudev/html-video-workflow
Local workspace: `codex-projects/html-video-workflow`

---

## 1. What the repository actually is

The upstream repository is **not** a large Python application. It is a compact
**Codex Skill package** that wraps a local-first HTML-to-video pipeline.

```
.
├─ SKILL.md                       # Codex skill entry (workflow + guardrails)
├─ README.md                      # bilingual overview
├─ agents/openai.yaml             # Codex/agent UI metadata
├─ assets/demo-us-study-2026.json # working sample project (6 scenes, zh-CN)
├─ references/project-schema.md   # V1 project JSON schema (prose + example)
├─ scripts/workflow.py            # THE pipeline (single file, ~300 LOC)
├─ scripts/sapi_tts.ps1           # Windows SAPI TTS helper (PowerShell)
└─ LICENSE                        # MIT
```

There is **no** `requirements.txt`, **no** `tests/`, **no** packaging metadata,
**no** Python package directory. Everything runs from `scripts/workflow.py`.

## 2. Existing capabilities (verified by reading source)

| Capability | Implementation | Notes |
|---|---|---|
| Source research | `workflow.py research --url ...` | urllib + `robotparser`, text extraction via `HTMLParser`, 18k char cap, 1s delay |
| Script/project planning | `workflow.py plan --topic ... --agent deepseek` | Direct DeepSeek API call (`DEEPSEEK_API_KEY`), `response_format=json_object`, JSON-only output |
| Project validation | `validate_project()` | title + 1..20 scenes; each scene needs `title`, `body`, `narration` |
| HTML rendering | `scene_html()` + Edge headless `--screenshot` | 10 templates, fixed 1280x720, inline CSS, one PNG per scene |
| Template gallery | `workflow.py gallery` | renders all 10 templates, writes `build/gallery.html` |
| TTS — SAPI | `sapi_tts.ps1` via `powershell.exe -File` | Windows only, zero download, low quality |
| TTS — MOSS | external CLI `moss-tts-nano` | ONNX/CPU default; optional voice clone with user reference clip |
| Composition | `ffmpeg` + `ffprobe` | per-scene segment (zoompan + fade), `concat` demuxer, libx264 crf 19, aac 160k |
| Source preservation | `project.sources[]` | URLs kept in project JSON and rendered footer |
| Safety rules | `SKILL.md` guardrails | untrusted web text, robots.txt, key hygiene, no unauthorized voice clone |

## 3. Design ideas worth preserving

1. **Structured JSON is the hand-off**, not a monolithic script — research →
   script → narration → visuals → render are separate, inspectable stages.
2. **Source URL preservation** — every factual claim is traceable.
3. **Local-first** — narration and rendering happen on the machine.
4. **Zero-download fallback** — SAPI means the pipeline still runs on a clean
   Windows box with no models.
5. **A skill file for agents** — `SKILL.md` makes the repo operable by Codex-like
   agents without a UI.

## 4. Limitations found

| # | Limitation | Impact |
|---|---|---|
| L1 | Single 300-line script holds research, LLM, TTS, render, compose | impossible to extend safely |
| L2 | Hardcoded `1280x720@30`, no vertical/shorts output | no Shorts/Reels |
| L3 | Chromium = Microsoft Edge only, hardcoded paths | breaks on non-Windows / non-Edge |
| L4 | Only two TTS engines, both Windows-centric | no Japanese/English quality path |
| L5 | No IR for prosody, emotion, pacing | narration sounds flat / "AI" |
| L6 | Scene duration = audio duration + 0.35s, always | no editorial rhythm, uniform shot length |
| L7 | One visual layout for all 10 templates (card + orb + tags + metric) | exactly the "animated PowerPoint" failure mode |
| L8 | No caching | re-render regenerates everything |
| L9 | No job model / resume | a failure at scene 6 restarts from scene 1 |
| L10 | No quality checks | silent audio, black frames or overflow go undetected |
| L11 | No hardware awareness | "prefer moss on CPU" is hardcoded advice in SKILL.md |
| L12 | No API / UI / MCP surface | agents must shell out to a Python script |
| L13 | `__pycache__/*.pyc` committed to git | repo hygiene |
| L14 | No tests, no schema file (schema is prose in markdown) | drift risk |
| L15 | DeepSeek-only LLM, no OpenAI-compatible abstraction | cannot switch backends |

## 5. Baseline commands (before refactor)

All relative to repository root:

```bash
# research
python scripts/workflow.py research --url https://example.com --output research.json

# plan (requires DEEPSEEK_API_KEY)
python scripts/workflow.py plan --topic "..." --research research.json --output project.json

# preview PNGs only (no TTS, no ffmpeg)
python scripts/workflow.py render --project assets/demo-us-study-2026.json \
    --template academic-blue --build build --preview-only

# full render (SAPI TTS + ffmpeg)
python scripts/workflow.py render --project assets/demo-us-study-2026.json \
    --template academic-blue --build build

# gallery of all 10 templates
python scripts/workflow.py gallery --project assets/demo-us-study-2026.json
```

Environment confirmed on this machine:
Python 3.13.14 (managed 3.13.12), Node v22.22.2, npm 10.9.7,
ffmpeg/ffprobe 9.0-full_build (gyan.dev), Microsoft Edge present at
`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`.

## 6. Compatibility commitment

`scripts/workflow.py` is **not moved and not modified** during Foundation. It
stays the reference implementation of the legacy path and is wrapped by
`src/html_video_workflow/legacy/adapter.py`, so:

* every command in §5 keeps working;
* the new Runtime can call the legacy renderer and legacy TTS as Providers;
* V1 project JSON remains loadable (auto-migrated to IR V2 in memory).

## 7. What is deliberately NOT carried forward

* The single-file script as the *only* entry point.
* Fixed 1280x720 output (replaced by output presets).
* Hardcoded Edge path (replaced by a browser resolver: Edge → Chrome → Playwright Chromium).
* Template-as-style (10 templates become 10 renderer *themes*; style becomes a
  render-independent `StyleProfile`).
