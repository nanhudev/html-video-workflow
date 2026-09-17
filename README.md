# HTML Video Workflow

**One prompt in. A finished video out.**

Type an idea. Get back an MP4 with narration, on-screen text, subtitles and a
soundtrack-free but properly paced edit — produced entirely on your own machine.

[![CI](https://github.com/nanhudev/html-video-workflow/actions/workflows/ci.yml/badge.svg)](https://github.com/nanhudev/html-video-workflow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/nanhudev/html-video-workflow?include_prereleases&sort=semver)](https://github.com/nanhudev/html-video-workflow/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[**⬇ Download for Windows**](../../releases/latest) ·
[Quick start](QUICKSTART.md) ·
[中文说明](#中文说明) ·
[Examples](docs/examples/) ·
[Status](docs/STATUS.md)

---

## Demo

![A 28-second video produced by this project: four scenes with Chinese narration, on-screen text and burned-in subtitles](docs/assets/demo.gif)

*28 seconds, 1920×1080, produced from the prompt `为什么本地 AI 很重要`. Real
Windows SAPI voice, real HTML/CSS rendering, real subtitles — no stock footage
and no external assets. Full file: [`docs/assets/demo.mp4`](docs/assets/demo.mp4),
and the numbers behind it in
[`docs/examples/01_explainer/result.json`](docs/examples/01_explainer/result.json).*

---

## What it does

Give it a topic. It writes a script, breaks it into scenes, lays each scene out
as HTML, screenshots it, synthesises the voice, times the subtitles against the
real audio, and muxes the whole thing into an MP4.

- **Runs locally.** No account, no upload, no per-video cost. Your topic and your
  documents stay on your disk.
- **Returns a real file**, not a storyboard or a draft. `create_video()` hands you
  a path to an H.264 MP4 that plays in anything.
- **Explains itself.** Every result carries `reasons`, `warnings` and `fallbacks`.
  A degradation is always recorded and never silent.
- **Works without a key.** With no AI model configured, the narration comes from
  built-in writing templates — and the result says so, instead of implying a
  model wrote it. See [Offline vs. AI writing](#offline-vs-ai-writing).
- **Nothing installed.** The Windows download bundles Python's runtime, the
  renderer's browser dependency and FFmpeg. Double-click and go.

> **Why is it called "HTML"?** HTML is the *rendering* engine, not the workflow.
> Scenes are composed as HTML and CSS and screenshotted, which is what makes the
> typography behave like a web page instead of like a slideshow. You never write
> any HTML, and you never see any.

---

## Quick start

**Windows, no toolchain:**

1. Download `html-video-windows-x64-*.zip` from
   [Releases](../../releases/latest) (~185 MB — FFmpeg is inside).
2. Unzip anywhere. Prefer a data drive: a one-minute video needs 1–2 GB of
   scratch space.
3. Double-click **`html-video.exe`**. A console window opens (leave it running)
   and your browser opens at <http://127.0.0.1:8787>.
4. Follow the seven-step wizard. Step 6 produces the video.

> First launch will show "Windows protected your PC" — the build is not
> code-signed. **More info → Run anyway.** Documented, not hidden.

**From source:**

```bash
python scripts/dev.py setup     # venv + dependencies
html-video doctor               # what this machine can actually do
html-video                      # open the studio in a browser
html-video generate "为什么本地 AI 很重要"
```

---

## Desktop app

The wizard is the intended path for anyone who does not want a terminal.

| Step | What you do | What it actually does |
| :--- | :--- | :--- |
| 1. Environment | nothing | Probes the machine for real: rendering, voice, disk. Each failure comes with the fix. |
| 2. Voice engine / AI writing | choose | Use the built-in writing, or connect an AI model. Connecting shows a key and a model; the base URL lives under Advanced. |
| 3. Topic | type an idea | Plus duration, aspect ratio and language. |
| 4. Writing style | pick a tone | Eight presets, each naming its audience. Hand-edited fields are never overwritten. |
| 5. Look | pick a structure and a skin | Template (how the argument is organised) and style (colour and type) are independent. |
| 6. Generate | one click | Progress is live and cancellable. |
| 7. Done | take the file | Playback, **Open file location**, copy path, and a note on where the words came from. |

**My Videos** lists what you have made, newest first, with thumbnails.

Developer surfaces — provider ids, hardware routing, renderer choice, the REST
API — are behind **Advanced**. They are not shown to someone who just wants a
video.

---

## Offline vs. AI writing

These are different products and the interface says which one you are getting.

| | No AI model configured | AI model configured |
| :--- | :--- | :--- |
| **Narration** | Built-in writing templates. Complete and structured, but formulaic. | Written by the model you configured, in the writing style you chose. |
| **Scenes, voice, subtitles, render** | **Real.** Identical to the connected path. | **Real.** |
| **Network** | Not used. | One call, to write the script. |
| **Reported as** | `narration_source: "rule"` | `narration_source: "llm"` |

> Works without an API key. Without an AI model configured, HTML Video Workflow
> uses built-in writing templates instead of pretending that a model wrote the
> narration.

Keys are stored in `数据目录\.env` on your machine and sent only to the endpoint
you configure. Any OpenAI-compatible API works.

## Voice

The verified configuration is the **Windows SAPI Chinese voice that ships with
the operating system**. `doctor` lists exactly which voices are installed, and
the pipeline measures the actual speaking rate of the voice it routes to
(3.35 CJK characters per second on the verification machine) rather than
assuming one. Re-measure on your own machine with
`python scripts/measure_speech_rate.py`.

Neural TTS adapters exist and route correctly, but **no neural voice is installed
on the machine this was verified against**, so that path is marked experimental
in [`docs/STATUS.md`](docs/STATUS.md) rather than claimed as working.

---

## CLI, Python and the REST API

```bash
html-video                                  # studio in the browser
html-video doctor                           # honest per-capability report
html-video generate "为什么本地 AI 很重要"    # straight to MP4
html-video presets                          # the eight writing styles
html-video generate "选题" --writing-preset how_to --duration 60
html-video generate "选题" --out D:\videos   # also copy the result there
```

```python
from html_video_workflow import create_video

result = create_video("为什么本地 AI 很重要", writing_preset="popular_science")
print(result.video_path, result.narration_source)
```

```http
POST /v1/videos   {"topic": "为什么本地 AI 很重要", "writing_preset": "popular_science"}
```

All entry points — CLI, Python SDK, REST API, MCP server and the desktop app —
construct the same `CreateVideoRequest` and call the same
`VideoRuntime.create_video()`. A capability cannot exist in one and be missing
from another. Full contract: [`docs/API.md`](docs/API.md).

---

## Templates and writing styles

Three independent choices, deliberately kept apart:

| | What it decides | Options |
| :--- | :--- | :--- |
| **Template** | how the argument is structured | `editorial_argument`, `data_story`, `product_demo`, `knowledge_primer`, `mechanism_explainer`, `documentary_walkthrough`, `social_short` |
| **Style** | colour, type and spacing | 6 style profiles |
| **Writing preset** | who the script is for, and in what tone | `popular_science`, `product_review`, `how_to`, `data_story`, `opinion`, `story`, `news_brief`, `pitch` |

Template ids and preset ids are separate namespaces — `data_story` appears in
both on purpose, meaning "this structure" and "this tone" respectively.

---

## How it works

```
topic ──▶ script ──▶ scenes ──▶ HTML ──▶ screenshots ──▶ voice ──▶ subtitles ──▶ MP4
         (rules or            (layout    (Chromium)      (SAPI /    (timed to
          a model)             engine)                   neural)    real audio)
```

Three properties are enforced by tests, because they are what keep the output
retargetable and the promises honest:

- **The intermediate representation never names a renderer.** A layer is
  `{type, role, content, layout, motion}`. No `remotionComponent`, no `cssClass`.
- **A claim is not a capability.** `ProviderSpec` declares; `probe()` checks.
  A probe may confirm or downgrade, never upgrade. Nothing is reported available
  without having been checked.
- **Timing follows the words.** The planner budgets against the measured speech
  rate, and the composer pads each segment by the same constant. A 28-second
  request produced a 28.4-second video.

---

## Honest limitations

- **No LLM key was configured on the verification machine**, so the AI-writing
  path is implemented and unit-tested but has not been run end to end against a
  real model here. Every example in this repository therefore reports
  `narration_source` as `"user"` or `"rule"` — never `"llm"`.
- **The first-run experience on a clean VM is not verified.** The CLI path the
  wizard calls is exercised, and the wizard has been driven over CDP, but
  "double-click on a fresh Windows install" remains unproven until someone does
  it. Treat it as unverified rather than assuming it works.
- **Rendering is slow**: roughly 20–30 seconds per scene at 1920×1080, because
  each scene is a real browser screenshot. Accepted, not optimised.
- **9:16 vertical output is experimental** — it renders, but the type scale was
  tuned for 16:9.
- **No avatar, image-generation, video-generation, music or ASR providers.**
  Absent rather than stubbed, so nothing silently degrades into one.
- **Windows only** for the packaged download. The Python package runs elsewhere,
  but the binaries and the SAPI voice path are Windows-specific.

Full, current, evidence-linked list: [`docs/STATUS.md`](docs/STATUS.md).

---

## Developers

```bash
python scripts/dev.py setup     # create the venv and install
python scripts/dev.py doctor    # report on this machine
python scripts/dev.py test      # pytest + UI type check
python scripts/dev.py studio    # build and serve the UI
python scripts/dev.py render examples/minimal-ir-v2.json
```

Packaging the Windows download:

```bash
python -m pip install pyinstaller
python scripts/pack_release.py --ffmpeg-bin D:\tools\ffmpeg\bin
# → dist/release/html-video-windows-x64-<version>.zip
```

Pushing a `v*` tag builds it in CI and attaches it to the GitHub Release.

Keep models, caches and job artifacts on a data drive via `HVW_HOME`
(for example `HVW_HOME=D:\html-video-workflow`). Windows, POSIX and Git Bash
path forms are all normalised; relative paths are rejected.

The original project-JSON workflow (`scripts/workflow.py`) is untouched and still
works — it exists to patch an existing project, not to create new videos.

### MCP

`SKILL.md` describes the agent-facing surface, so an MCP client can call
`create_video` with the same request object the CLI builds.

---

## Contributing

Issues and pull requests are welcome. The most useful things to send:

- A reproducible failure from the packaged build, with `html-video doctor` output.
- A topic where the narration or the layout comes out badly, with the MP4.

Please run `python scripts/dev.py test` before opening a PR. See
[`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md) and
[`docs/development/ARCHITECTURE.md`](docs/development/ARCHITECTURE.md).

## Security

See [`SECURITY.md`](SECURITY.md). API keys are never written to logs, project
files or job artifacts.

## License

MIT — see [LICENSE](LICENSE).

---

## 中文说明

**输入一个选题，输出一条成片。**

写下你想讲什么，几十秒后拿到一条带旁白、字幕和画面的 MP4 —— 全部跑在你自己的电脑上。

[**⬇ 下载 Windows 版**](../../releases/latest)：解压后双击 `html-video.exe`，
浏览器自动打开，跟着七步向导走完即可。**不需要安装 Python、Node 或 FFmpeg**，
它们要么已打包，要么根本用不上。

- **不填 API Key 也能用。** 不配置 AI 模型时，旁白由内置写作模板生成；
  画面、配音、字幕完全是真实的，结果页会明确标出文案是**模板生成**还是**模型生成**。
- **配音**使用系统自带的 Windows 中文语音（SAPI）。程序会实测所选语音的语速，
  而不是假设一个数字。
- **音频时长**按实测语速排布：请求 28 秒，实得 28.4 秒，且没有为凑时长删改文案。

**为什么叫 HTML Video Workflow**：HTML 是**渲染引擎**，不是你的工作流。
画面以 HTML/CSS 排版后截图，所以字体和留白像网页一样可控。你不需要写任何 HTML。

| 文档 | 内容 |
| :--- | :--- |
| [`QUICKSTART.md`](QUICKSTART.md) | 五分钟上手 |
| [`docs/STATUS.md`](docs/STATUS.md) | 唯一权威状态：现在稳定什么、实验什么、缺什么 |
| [`docs/examples/`](docs/examples/) | 三个真实成片，含配置与实测数据 |
