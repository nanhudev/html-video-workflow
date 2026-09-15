# HTML Video Workflow · 本地视频生成工作台

**输入一个选题，输出一条带配音、字幕和画面的 MP4。整个过程跑在你自己的电脑上。**

不用写代码，不用注册账号，不用把选题和素材上传到别人的服务器。

[**⬇ 下载 Windows 版**](../../releases/latest) ·
[五分钟上手](QUICKSTART.md) ·
[遇到问题](#遇到问题怎么办) ·
[English](#english)

---

## 下载就能用

### ① 下载

打开 [Releases](../../releases/latest) 页面，下载 `html-video-windows-x64-*.zip`（约 185 MB —— 里面打包了完整的 FFmpeg，所以偏大，但换来的是不用再装任何东西）。

### ② 解压

解压到任意文件夹，例如 `D:\html-video`。

> 建议放在 **D 盘或其他数据盘**。一条一分钟的视频，临时文件加成品大约需要 1–2 GB；
> 放在系统盘会让 C 盘越来越紧张。

### ③ 双击 `html-video.exe`

- 会弹出一个黑色窗口 —— 那是本地服务，**不要关掉它**（关掉界面就打不开了）
- 等几秒钟，浏览器会自动打开
- 如果没自动打开，手动访问 <http://127.0.0.1:8787>

不需要装 Python，不需要装 Node.js，FFmpeg 已经打包在 `bin` 文件夹里。

> **第一次运行会被 Windows 拦一下。** 出现「Windows 已保护你的电脑」是正常的 ——
> 这个版本没有购买代码签名证书。点「更多信息」→「仍要运行」即可。

---

## 然后跟着向导走七步

界面左侧只有两个入口：**「开始创作」**和**「我的作品」**。创作是一条单向的向导：

| 步骤 | 你在做什么 | 说明 |
| :--- | :--- | :--- |
| **① 环境自检** | 什么都不用做 | 程序**真的去探测**这台电脑：能不能合成视频、有没有中文配音、磁盘够不够。有问题的项会直接告诉你**怎么修**，例如"安装 FFmpeg 后重启本程序" |
| **② 文案引擎** | 决定谁写旁白 | 填一个 API Key 让大模型写文案，或者选择离线（**不填也能用**，见下一节）。填了之后可以点「测试」——它会真的调用一次，而不是只告诉你"已保存" |
| **③ 选题** | 输入你想讲什么 | 一段话就行。顺手选时长（30/60/90/120 秒）、画面比例（横屏 16:9 / 竖屏 9:16 / 方形 1:1）和语言 |
| **④ 写作风格** | 用哪种方式讲 | 八种写法，每种都写明了受众和口吻：科普解说、产品测评、教程步骤、数据解读、观点评论、故事化叙事、新闻速览、项目推介。**你手改过的字段不会被覆盖** |
| **⑤ 模板与配色** | 长什么样 | 版式结构（怎么组织论点）和配色皮肤是两个独立的选项，可以自由组合 |
| **⑥ 生成** | 点「开始生成」 | 实时进度，随时可以取消。这一步包含写作、配音、逐场景截图、合成和质检 |
| **⑦ 完成** | 拿走视频 | 页面上直接播放 · **打开文件位置**（在资源管理器里选中文件）· 复制完整路径 |

生成过的视频都留在左侧 **「我的作品」** 里，带缩略图，随时回看。

---

## 要不要填 API Key？

**不填也能用。**

| | 离线（不填 Key） | 填了 API Key |
| :--- | :--- | :--- |
| 旁白文案 | 由内置规则模板生成，结构完整但比较程式化 | 由你配置的大模型按选定的写作风格撰写 |
| 画面、配音、字幕 | **都是真实的**，和联网时完全一样 | 同左 |
| 需要联网 | 否 | 只在写文案时调用一次 |

程序不会替你假装：结果页会明确标出这一次的文案是**规则生成**还是**模型生成**。

API Key 只保存在本机的配置文件里（`数据目录\.env`），不会上传到任何第三方服务器。
支持任何 OpenAI 兼容接口 —— 界面里预置了 DeepSeek、OpenAI、Moonshot、硅基流动的常用地址。

---

## 出片在哪？

- **成品视频**：数据目录下的 `outputs` 文件夹
- **数据目录**：程序优先选择 D/E 盘，形如 `D:\html-video-workflow`；没有第二个盘时用 `%USERPROFILE%\.html-video-workflow`
- 具体路径就写在启动时那个黑色窗口里，界面上点「打开文件位置」也能直接定位

想换位置：设置环境变量 `HVW_HOME` 指向你想要的目录，然后重启程序。

---

## 遇到问题怎么办

先看界面上的 **「环境自检」** —— 它列出的每一项都带了修复方法。

| 现象 | 原因与处理 |
| :--- | :--- |
| 首次运行弹出「Windows 已保护你的电脑」 | 没有代码签名证书，属正常。点「更多信息」→「仍要运行」 |
| 双击后浏览器没反应 | 看黑色窗口里打印的「界面」地址，手动在浏览器打开；确认窗口没有被关掉 |
| 提示端口被占用 | 黑色窗口里会报错。换端口启动：`html-video.exe --port 8899` |
| 视频没有声音 | 系统缺少中文语音包。设置 → 时间和语言 → 语言和区域 → 中文(简体) → 语言选项 → 语音 → 添加 |
| 生成很慢 | 渲染要逐场景调用浏览器截图，属正常。可在「环境自检」里把运行档位改成 `fast` |
| 提示找不到 FFmpeg | 用源码运行时才会出现。发布版自带；源码运行请自行安装 FFmpeg 并加入 PATH |
| 想确认机器能不能用 | 命令行运行 `html-video.exe doctor`，得到一份诚实的体检报告 |

---

## 其他用法

发布版里的 `html-video.exe` 本身就是完整的命令行工具。
从源码安装后，同一个 `html-video` 命令还提供 Python SDK、REST API 和 MCP server。

```bash
html-video                                  # 等同于双击：启动界面并打开浏览器
html-video doctor                           # 检查这台机器，逐项给出能不能用
html-video generate "为什么本地 AI 很重要"    # 不开界面，直接出片
html-video presets                          # 列出八种写作风格
html-video generate "选题" --writing-preset how_to --duration 60
html-video generate "选题" --out D:\videos   # 顺便把成品拷到指定目录
```

```python
from html_video_workflow import create_video

result = create_video("为什么本地 AI 很重要", writing_preset="popular_science")
print(result.video_path, result.narration_source)   # 出片路径，以及文案是规则还是模型写的
```

```http
POST /v1/videos   {"topic": "为什么本地 AI 很重要", "writing_preset": "popular_science"}
```

五个入口（CLI、Python SDK、REST API、MCP server、图形界面）**共用同一个实现**，
都构造同一个 `CreateVideoRequest` 并调用 `VideoRuntime.create_video()`。
所以不存在"某个能力只有一个入口有"的情况。完整契约见 [`docs/API.md`](docs/API.md)。

---

## 它凭什么不一样

大多数自动出片的演示只给你一个文件，你没法追问：为什么用这个模板、为什么是 32 秒而不是你要的 20 秒。
这个项目把每个决策都留在明面上：

- **每个结果都带 `reasons`、`warnings`、`fallbacks`** —— 降级一定会被记录，绝不静默发生
- **没有探测就没有"就绪"** —— `ProviderSpec` 只是声明，`probe()` 才是事实；能力只会被确认或降级，永远不会被假设
- **画面与渲染器解耦** —— 中间表示（IR V2）里的图层只描述 `{类型, 角色, 内容, 版式, 动效}`，不出现任何渲染器或 CSS 类名
- **环境自检是真的在跑探测**，不是打印一行"OK"

---

## 运行要求

- **发布版**：Windows 10/11 64 位 + 系统自带的 Edge 浏览器。中文配音需要系统中文语音包
- **源码运行**：Python 3.11+、Node.js 20+（仅构建界面时需要）、FFmpeg、Chromium 内核浏览器

---

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [`QUICKSTART.md`](QUICKSTART.md) | 五分钟上手 |
| [`CURRENT_STATUS.md`](CURRENT_STATUS.md) | 现在**验证可用**的有什么，不可用的有什么 |
| [`ROADMAP.md`](ROADMAP.md) | 阶段规划，以及明确的"不做"清单 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 分层、边界与设计规则 |
| [`DECISIONS.md`](DECISIONS.md) | 决策记录（D-001 …）及理由 |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | 环境搭建、运行、测试、约定、如何新增 Provider |
| [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md) | 新 Agent / 新贡献者的接手入口 |
| [`VIDEO_IR_V2.md`](VIDEO_IR_V2.md) | IR V2 参考 |
| [`PROVIDER_SPEC.md`](PROVIDER_SPEC.md) | 如何写一个 Provider |
| [`HARDWARE_ROUTING.md`](HARDWARE_ROUTING.md) | 硬件探测与路由行为 |
| [`docs/API.md`](docs/API.md) | REST 契约 |
| [`SKILL.md`](SKILL.md) | 给 Agent 用的技能说明 |

---

## 开发

```bash
python scripts/dev.py setup     # 创建虚拟环境并安装依赖
python scripts/dev.py doctor    # 对当前机器给出诚实报告
python scripts/dev.py test      # pytest + 界面类型检查
python scripts/dev.py studio    # 构建并启动界面
python scripts/dev.py render examples/minimal-ir-v2.json
```

打包发布版（需要 PyInstaller）：

```bash
python -m pip install pyinstaller
python scripts/pack_release.py --ffmpeg-bin D:\tools\ffmpeg\bin
# → dist/release/html-video-windows-x64-<版本>.zip
```

推一个 `v*` 标签会自动触发 [`.github/workflows/release.yml`](.github/workflows/release.yml)，
在 CI 里构建并上传到 GitHub Release。

模型、缓存、任务产物这类大文件应该放在数据盘：用 `HVW_HOME` 指向目标位置
（例如 `HVW_HOME=D:\html-video-workflow`）。程序会自动归一化 Windows、POSIX、
Git Bash 三种写法，并拒绝相对路径。

原有的旧流程（`scripts/workflow.py`、项目 JSON、十套 HTML/CSS 模板）没有被改动，
仍然完整可用 —— 它的用途是修补已有项目，而不是制作新视频。

## License

MIT

---

## English

**Type a topic, get a narrated MP4 — entirely on your own machine.**

No code, no account, no upload. Download `html-video-windows-x64-*.zip` from
[Releases](../../releases/latest), unzip it, and double-click `html-video.exe`.
Your browser opens at <http://127.0.0.1:8787> and a seven-step wizard walks you
through environment checks, narration engine, topic, writing style, template and
colour, generation, and the finished file. Python, Node.js and FFmpeg are *not*
required — FFmpeg ships inside the zip.

**An API key is optional.** Without one the narration is written by built-in
rules; the visuals, voice and subtitles are real either way, and the result page
states which of the two produced the words. With one, any OpenAI-compatible
endpoint works. The key is stored locally and never sent anywhere else.

Every entry point — the CLI, the Python SDK, the REST API, the MCP server and
the GUI — builds the same `CreateVideoRequest` and calls the same
`VideoRuntime.create_video()`, so no capability exists in one and not the others.

What sets this apart is that nothing is hidden: every result carries `reasons`,
`warnings` and `fallbacks`; a `ProviderSpec` is only a claim that a `probe()`
confirms or downgrades; and the renderer-neutral IR V2 describes layers as
`{type, role, content, layout, motion}` without ever naming a renderer or a CSS
class.

Source builds additionally support `html-video doctor`,
`html-video generate "topic"`, and a documented REST contract in
[`docs/API.md`](docs/API.md). Full requirements: Python 3.11+, Node.js 20+ (for
building the UI), FFmpeg, and a Chromium-based browser. See
[`DEVELOPMENT.md`](DEVELOPMENT.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).
