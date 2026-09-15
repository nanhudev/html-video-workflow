# HTML Video Workflow

English | [简体中文](#简体中文)

**One prompt in. A complete MP4 out.**

A local-first, agentic video runtime for turning sourced research into narrated short videos. One call runs the whole pipeline — source, topic, template, style, script, storyboard, render, voice, composition and quality control — and hands back a real MP4 plus the reasons for every decision it made.

```bash
html-video generate "Why local AI matters" -o result.mp4
```

```python
from html_video_workflow import create_video

result = create_video("Why local AI matters", output="result.mp4")
```

```http
POST /v1/videos   {"prompt": "Why local AI matters", "duration_sec": 45}
```

```text
MCP: create_video(prompt="Why local AI matters")
```

Four entry points, one implementation. The CLI, the Python SDK, the REST API and
the MCP server all build the same `CreateVideoRequest` and call
`VideoRuntime.create_video()` — so no capability can exist in one entry point
and not another. The Studio GUI calls the same method.

## Why this project

Most automated video demos hide their decisions inside a single script, and the
result is a video you cannot interrogate: why *this* template, why *that*
length, why is it 32 seconds when you asked for 20. This project keeps every
decision in the open. Each result carries `reasons`, `warnings` and `fallbacks`;
a degradation is always recorded, never silent.

## What it includes

- **One-click generation** from a prompt, a topic, a script or a source document
- **Sources** — web pages, GitHub repos, Markdown, local files, plain text
- **Planning** — topic suggestion, template selection, style selection, script
  and storyboard, each with a stated reason
- **Templates and styles** — the structure of the argument and the skin are
  independent choices
- **A renderer-neutral IR (V2)** — layers carry `{type, role, content, layout,
  motion}` and never name a renderer or a CSS class
- **Honest providers** — a `ProviderSpec` is a claim, a probe is the check, and
  a capability can only be confirmed or downgraded
- **Local speech** — MOSS-TTS-Nano or Windows SAPI, chosen by probe
- **FFmpeg composition and QC** — measured on the real file, not asserted
- **Agent-ready** — a Skill, an MCP server and a versioned REST API

## Workflow

1. Give it a prompt (or a source to ground it in).
2. It plans: topic, template, style, script, storyboard.
3. It renders each scene and synthesises the narration.
4. It composes the MP4 and measures it.
5. You read `reasons`, `warnings` and `fallbacks` and know exactly what you got.

Start with [`QUICKSTART.md`](QUICKSTART.md) for the five-minute path, or
[`docs/API.md`](docs/API.md) for the full contract. Agents should read
[`SKILL.md`](SKILL.md).

The legacy entry points (`scripts/workflow.py`, project JSON, the ten HTML/CSS
templates) are unchanged and remain fully functional — use them to repair an
existing project, not to make a new video.

## Architecture Foundation

The project is being evolved into a **local-first agentic video studio**: the agent decides, the IR describes, providers execute, the runtime schedules, the studio visualises, and a quality system verifies.

The foundation layer is now in place and coexists with — it does not replace — the legacy workflow:

- **Video Project IR V2** — a renderer-neutral project model (`Project ▸ Sequence ▸ Scene ▸ Shot ▸ Layer`). Layers carry `{type, role, content, layout, motion}` and never name a renderer, a CSS class, or a component.
- **Provider system** — providers declare a `ProviderSpec` (a claim) and expose `probe()` (the real check). A capability is only ever *confirmed* or *downgraded* by a probe, never assumed.
- **Hardware profiler** — probes the live machine instead of hardcoding facts.
- **Capability-based routing** — hard filters (availability, language, VRAM budget, user locks) run before weighted scoring, and every plan carries a human-readable `reason[]`.
- **Runtime** — `Job ▸ Task ▸ Step ▸ Artifact`, append-only `events.jsonl`, content-addressed caching, and explicit fallback recording.
- **Studio** — a local UI for jobs, providers, hardware, and quality reports.
- **Doctor & smoke test** — honest status reporting for the real machine.

Nothing in this layer reports `Ready` or `Available` without having probed for it.

### Documentation map

| Document | Contents |
| --- | --- |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Layer map, boundaries, and design rules |
| [`CURRENT_STATUS.md`](CURRENT_STATUS.md) | What is verified working right now, and what is not |
| [`ROADMAP.md`](ROADMAP.md) | Phase plan, with an explicit out-of-scope list |
| [`DECISIONS.md`](DECISIONS.md) | Decision records (D-001 …) with rationale |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Setup, running, testing, conventions, adding a provider |
| [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md) | Entry point for a new agent or contributor picking this up |
| [`VIDEO_IR_V2.md`](VIDEO_IR_V2.md) | The IR V2 reference |
| [`PROVIDER_SPEC.md`](PROVIDER_SPEC.md) | How to write a provider |
| [`HARDWARE_ROUTING.md`](HARDWARE_ROUTING.md) | Profiling and routing behaviour |
| [`docs/research/README.md`](docs/research/README.md) | Research findings and open questions |

### One-command development

```bash
python scripts/dev.py setup     # create the venv and install deps
python scripts/dev.py doctor    # honest report on this machine
python scripts/dev.py test      # pytest + studio typecheck
python scripts/dev.py studio    # build and serve the studio UI
python scripts/dev.py render examples/minimal-ir-v2.json
```

Heavy state — models, caches, job artifacts — belongs on a data drive, not the system drive. Point `HVW_HOME` at it (e.g. `HVW_HOME=D:\html-video-workflow`); the app normalises Windows, POSIX and Git Bash spellings of the same path and rejects relative values.

## Requirements

Python 3.11+, a Chromium-compatible browser for HTML rendering, and FFmpeg. Windows SAPI is available as a zero-download narration fallback on Windows.

The foundation layer additionally needs Node.js 20+ to build the studio UI. Full prerequisites are in [`DEVELOPMENT.md`](DEVELOPMENT.md).

## License

MIT

## 简体中文

这是一个可复用、以本地运行为主的短视频生产流水线，可将带来源的研究资料转换为有旁白的成片。流程由资料收集、结构化分镜、HTML/CSS 渲染、本地语音合成和 FFmpeg 合成组成。

它的重点不是把所有步骤藏进一个脚本，而是用经过校验的 JSON 项目文件连接研究、写作、旁白、画面与渲染。每个阶段都可以独立检查、替换或自动化。

主要能力包括十套 HTML/CSS 视觉模板、MOSS-TTS-Nano 或 Windows SAPI 旁白、引用来源保留，以及 FFmpeg 成片合成。完整命令与安全规则见 [`SKILL.md`](SKILL.md)，项目格式见 [`references/project-schema.md`](references/project-schema.md)。

## 架构基础层

项目正在演进为一个**本地优先的智能体视频工作室**：Agent 负责决策，IR 负责描述，Provider 负责执行，Runtime 负责调度，Studio 负责可视化，质量体系负责校验。

基础层已经落地，它与原有流程**共存而非替换**：

- **Video Project IR V2** —— 与渲染器无关的项目模型（`Project ▸ Sequence ▸ Scene ▸ Shot ▸ Layer`）。图层只承载 `{type, role, content, layout, motion}`，不会出现渲染器名、CSS 类名或组件名。
- **Provider 体系** —— Provider 声明 `ProviderSpec`（主张），并提供 `probe()`（真实探测）。能力只会被探测**确认**或**降级**，绝不假设。
- **硬件探测** —— 实时探测当前机器，不硬编码任何机器事实。
- **基于能力的路由** —— 先做硬性过滤（可用性、语言、显存预算、用户锁定），再加权打分；每个方案都附带可读的 `reason[]`。
- **Runtime** —— `Job ▸ Task ▸ Step ▸ Artifact`，append-only 的 `events.jsonl`，内容寻址缓存，回退链路全程留痕。
- **Studio** —— 查看任务、Provider、硬件与质量报告的本地界面。
- **doctor 与冒烟测试** —— 对真实机器给出诚实的状态报告。

这一层中不会有任何组件在未经探测的情况下显示 `Ready` 或 `Available`。

### 一条命令开发

```bash
python scripts/dev.py setup     # 创建虚拟环境并安装依赖
python scripts/dev.py doctor    # 对当前机器给出诚实报告
python scripts/dev.py test      # pytest + Studio 类型检查
python scripts/dev.py studio    # 构建并启动 Studio
python scripts/dev.py render examples/minimal-ir-v2.json
```

依赖与大文件应放在数据盘而非系统盘：用 `HVW_HOME` 指向目标位置（例如 `HVW_HOME=D:\html-video-workflow`）。程序会自动归一化 Windows、POSIX、Git Bash 三种写法，并拒绝相对路径。

文档索引：[`ARCHITECTURE.md`](ARCHITECTURE.md)（分层与边界）、[`CURRENT_STATUS.md`](CURRENT_STATUS.md)（当前真实验证状态）、[`ROADMAP.md`](ROADMAP.md)（阶段规划）、[`DECISIONS.md`](DECISIONS.md)（决策记录）、[`DEVELOPMENT.md`](DEVELOPMENT.md)（开发指南）、[`AGENT_HANDOFF.md`](AGENT_HANDOFF.md)（接手入口）。
