# HTML Video Workflow

English | [简体中文](#简体中文)

A reusable, local-first pipeline for turning sourced research into narrated short videos. It keeps the production process explicit: source collection, structured scene planning, HTML/CSS rendering, local speech synthesis, and final FFmpeg composition.

## Why this project

Most automated video demos hide their decisions inside a single script. This project uses a validated JSON project file as the hand-off between research, writing, narration, visuals, and rendering. Each stage can be reviewed, replaced, or automated independently.

## What it includes

- Source-aware research and script planning
- A documented JSON schema for scenes and citations
- Ten reusable HTML/CSS visual templates
- Narration through MOSS-TTS-Nano or Windows SAPI
- Frame rendering and MP4 composition with FFmpeg
- A Codex skill definition for repeatable agent-driven runs

## Workflow

1. Collect allowed source material and preserve its URLs.
2. Build and validate a structured video project.
3. Generate narration locally.
4. Render each scene with an HTML/CSS template.
5. Compose the final video with FFmpeg.

Start with [`SKILL.md`](SKILL.md) for the complete workflow and safety rules. The project format is documented in [`references/project-schema.md`](references/project-schema.md), and [`assets/demo-us-study-2026.json`](assets/demo-us-study-2026.json) provides a working example.

## Requirements

Python 3.11+, a Chromium-compatible browser for HTML rendering, and FFmpeg. Windows SAPI is available as a zero-download narration fallback on Windows.

## License

MIT

## 简体中文

这是一个可复用、以本地运行为主的短视频生产流水线，可将带来源的研究资料转换为有旁白的成片。流程由资料收集、结构化分镜、HTML/CSS 渲染、本地语音合成和 FFmpeg 合成组成。

它的重点不是把所有步骤藏进一个脚本，而是用经过校验的 JSON 项目文件连接研究、写作、旁白、画面与渲染。每个阶段都可以独立检查、替换或自动化。

主要能力包括十套 HTML/CSS 视觉模板、MOSS-TTS-Nano 或 Windows SAPI 旁白、引用来源保留，以及 FFmpeg 成片合成。完整命令与安全规则见 [`SKILL.md`](SKILL.md)，项目格式见 [`references/project-schema.md`](references/project-schema.md)。
