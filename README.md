# HTML Video Workflow / HTML 视频流水线

从资料研究到成片输出的一体化短视频工具链：结构化脚本、可追溯来源、十套 HTML/CSS 视觉模板、MOSS-TTS 或 Windows SAPI 旁白，以及 FFmpeg 合成。

An end-to-end short-video pipeline covering sourced research, structured scripts, ten HTML/CSS visual templates, MOSS-TTS or Windows SAPI narration, and FFmpeg composition.

## Pipeline / 流程

1. Research allowed pages and preserve source URLs / 研究允许抓取的页面并保留来源。
2. Plan scenes into a validated JSON project / 生成并校验场景 JSON。
3. Synthesize narration locally / 本地合成旁白。
4. Render HTML/CSS frames / 渲染 HTML/CSS 画面。
5. Compose the final MP4 with FFmpeg / 使用 FFmpeg 合成 MP4。

See `SKILL.md` for commands and safety guardrails. See `references/project-schema.md` for the project format.

命令与安全规则见 `SKILL.md`，项目数据结构见 `references/project-schema.md`。

## License

MIT
