# Status

**Version 0.4.0 · verified 2026-09-17 on Windows 11 x64**

This is the single authoritative statement of what works. If any other document
in this repository disagrees with this file, this file is right and the other one
is stale — please open an issue about it rather than trusting the older text.

Three categories, and nothing in between: something is **stable**, it is
**experimental**, or it is a **known gap**. There is deliberately no "planned"
category; intentions live in the issue tracker, not in a status page.

---

## Stable today

Verified on a clean Windows machine with an NVIDIA RTX 2070, and again from the
frozen (PyInstaller) build.

| Capability | What "stable" means here |
| :--- | :--- |
| **One prompt → one MP4** | `create_video("topic")` returns a finished H.264 file. CLI, Python SDK, REST API, MCP server and the GUI all build the same `CreateVideoRequest` and call the same `VideoRuntime.create_video()`. |
| **HTML/CSS rendering** | Scenes are composed as HTML and screenshotted through a Chromium-based browser. Nine layout primitives, nine motion presets, safe areas, a type scale. |
| **Windows SAPI Chinese voice** | Real speech through the installed system voice. Measured at **3.35 CJK chars/sec** on this machine; `scripts/measure_speech_rate.py` re-measures it anywhere. |
| **Subtitles** | SRT generation and burn-in, timed against the rendered segments. |
| **Duration adherence** | The planner budgets against the measured speech rate. A 28 s request produced a 28.4 s video (**1.4 %** deviation) with no narration trimmed. |
| **Templates and styles** | 7 templates × 6 styles, composed independently. Structure, skin and writing preset are three separate namespaces. |
| **Portable Windows build** | `html-video.exe` + bundled `ffmpeg`/`ffprobe`. Double-click opens a browser; Python, Node and FFmpeg are not required. |
| **`doctor`** | Real probes, reported as installed-and-usable vs absent. It never says "Ready" without having checked. |
| **Offline operation** | Every stage except optional model-written narration runs with no network at all. |

## Experimental

Usable, with caveats worth knowing before you rely on it.

| Capability | Caveat |
| :--- | :--- |
| **9:16 vertical** | Renders correctly and the layout engine adapts, but the type scale was tuned for 16:9 and some headlines still read small. |
| **`social_short` template** | Shortest scenes of the set; the pacing is more assertive than the others and suits some topics badly. |
| **Neural TTS adapters** | The adapter code, routing and probing are complete and tested. No neural voice is installed on the verification machine, so this path has not been exercised end to end — only SAPI has. |
| **Hardware routing** | CUDA / Vulkan / DirectML detection works. A machine with virtual display adapters reports `VRAM unknown`, which keeps those adapters out of scoring. |
| **`legacy_html` renderer** | Retained for the original project-JSON workflow. New work should use `advanced_html`. |

## Known gaps

Honest list. Each of these is a real limitation, not a roadmap item.

- **No LLM key is configured on the verification machine.** The AI-writing path
  is implemented, routed and unit-tested, but no end-to-end run against a real
  model has been performed here. Every demo in `docs/examples/` therefore reports
  `narration_source: "user"` or `"rule"` — never `"llm"`. See
  [`AGENT_HANDOFF.md`](development/AGENT_HANDOFF.md) for how to verify it.
- **Providers that are not implemented at all:** avatar, image generation,
  video generation, music, ASR. They are absent rather than stubbed, so nothing
  can silently fall back to them.
- **Providers present but unavailable on a clean machine:** `moss`
  (binary absent), `aivisspeech` (engine not running), `neural_sidecar`
  (`HVW_NEURAL_TTS_URL` unset), `openai_compatible*` (no key). `doctor` reports
  each as unavailable rather than hiding them.
- **The GUI wizard has not been walked by a human on a fresh machine.** It was
  driven over CDP, and the CLI path it calls is real, but the "double-click on a
  clean VM" test is not something this repository can claim yet. Until it is run,
  treat first-run behaviour as unverified.
- **No code-signing certificate**, so Windows SmartScreen warns on first launch.
  The README documents the click-through.
- **Render time is dominated by per-scene screenshots** — roughly 20–30 s per
  scene at 1920×1080. This is accepted, not optimised.

## How the claims above were checked

| Claim | Evidence |
| :--- | :--- |
| Duration adherence | `docs/examples/01_explainer/result.json` — 28 s requested, 28.4 s delivered, `warnings: []`. |
| Speech-rate calibration | `scripts/measure_speech_rate.py`, and `tests/test_phase3_product.py::test_the_estimator_agrees_with_measured_sapi_timing` against five real SAPI timings. |
| On-screen text is never cut mid-word | `tests/test_phase3_product.py::test_no_on_screen_text_ends_mid_word`. |
| Plan and render agree on scene padding | `tests/test_phase3_product.py::test_the_planner_and_the_composer_pad_a_scene_by_the_same_amount`. |
| Nothing is reported available without a probe | `tests/` provider suite; `doctor` prints `??` (present, unusable) apart from `--` (absent). |

## History

Superseded snapshots and phase reports are kept in [`history/`](history/) and are
**not** current: `CURRENT_STATUS.md`, `FOUNDATION_REPORT.md`, `ROADMAP.md`,
`PHASE1_TTS_REPORT.md`, `PHASE3_PRODUCTIZATION_REPORT.md`.
