# Current Status

**Version:** 0.4.0 · **Phase:** Non-technical GUI + portable release (PHASE 4) ·
**Last verified:** 2026-09-16 · **Branch:** `phase3-productization`

One prompt in, one MP4 out, through five entry points that share one
implementation — and, since PHASE 4, a download-and-double-click path for people
who will never open a terminal. See `docs/PHASE3_PRODUCTIZATION_REPORT.md` for
the pipeline account and `docs/API.md` for the contract.

This file is a snapshot, not a plan. For direction see `ROADMAP.md`; for the
reasons behind the architecture see `DECISIONS.md`.

---

## PHASE 4 — the GUI wizard and the downloadable build

The Phase 3 product still assumed a terminal. Phase 4 adds the path that does not.

### The wizard

`apps/studio/src/wizard/` — seven steps, hash-routed (`#create/N`), separate from
the developer pages which moved behind an "advanced" section:

| Step | Page | What it does |
|---|---|---|
| 1 | 环境自检 | `GET /v1/setup/status` — real probes, Chinese labels, a fix instruction per failure |
| 2 | 文案引擎 | `POST /v1/setup/llm` (save) and `/v1/setup/llm/test` (try without keeping) |
| 3 | 选题 | topic, duration, aspect, language; `GET /v1/topics/suggest` for angles |
| 4 | 写作风格 | `GET /v1/presets` — 8 writing presets, non-destructive: a preset only fills fields the user has not hand-edited |
| 5 | 模板与配色 | templates × styles, with swatches |
| 6 | 生成 | `POST /v1/videos?wait=false`, then poll `GET /v1/videos/{id}` |
| 7 | 完成 | inline playback, 打开文件位置, copy path, provenance, warnings, QC |

`我的作品` (`pages/Works.tsx` + `GET /v1/outputs`) lists finished videos newest
first with thumbnails, playback via `GET /v1/outputs/{file}`, and reveal/open via
`POST /v1/desktop/reveal|open`.

Verified end to end in a real browser on 2026-09-16 with
`scripts/ui_walkthrough.py --render --quick`, which drives headless Edge over CDP,
performs a genuine 30-second render through the wizard, and asserts on DOM state
(nine screenshots, 1 m 23 s wall clock). It is a script rather than a manual check
on purpose: this environment cannot read image files, so a screenshot proves
nothing by itself.

### Three concepts that were one

| Concept | Question it answers | Where |
|---|---|---|
| **Template** | what the video is *made of* (beats, layouts, scene count) | `templates/builtins/*.json` |
| **Style** | what it *looks like* (colour, type, spacing) | `templates/builtins/styles.json` |
| **Writing preset** | how it is *written* (who is talking, to whom, under which rules) | `templates/builtins/presets.json` |

Preset ids are a **separate namespace** from template ids. `data_story` exists in
both on purpose — the preset "数据解读" recommends the template "Data Story".

### The portable build

```
dist/release/html-video-windows-x64-<version>.zip
  html-video/
    html-video.exe        双击运行 → 自动打开 http://127.0.0.1:8787
    bin/ffmpeg.exe        自带，用户无需安装
    bin/ffprobe.exe
    使用说明.txt
```

Built by `scripts/pack_release.py` from `packaging/html-video.spec` (PyInstaller
one-dir). Frozen-mode path resolution lives in `config/paths.py`
(`is_frozen`/`bundle_root`/`resource_dir`/`bin_dir`); `ffmpeg/service.py` and
`hardware/profile.py` resolve tools in the order env → bundled `bin/` → PATH, and
`sapi.py` loads its `.ps1` from `resource_dir()`.

`.github/workflows/release.yml` triggers on a `v*` tag, installs FFmpeg, builds
and smoke-tests the frozen exe (`doctor`, `/health`, a real `generate` → MP4), and
uploads the zip to the GitHub Release.

### What the GUI can and cannot promise

- **The API key is optional and the UI says so.** Offline, the narration is
  written by rules; the visuals, voice and subtitles are real, and the result page
  names which of the two produced the words (`narration_source`).
- **Saving and working are separate facts.** `POST /v1/setup/llm` writes the key,
  rebuilds the providers, then probes — a stored-but-broken key is reported as
  broken, not as a green tick.
- **Desktop operations are path-contained.** `utils/desktop.py::resolve_within`
  resolves symlinks and `..` before comparing, so "open this file" is not a
  remote file-opener for the rest of the machine.

## Verified working

Everything below was executed on the development machine, not inferred from code.

### Test suite

```
pytest tests             → 389 passed, 0 failures, 0 errors, 0 skipped
npm run build            → built
python scripts/export_schema.py --check  → OK (schema matches models)
```

Read the count from the junit report (`--junitxml`), not the console: this
runner kills long-lived child processes, so a console summary line is not
trustworthy here.

CI is the authority. `.github/workflows/ci.yml` runs one job per test file on
ubuntu, plus a package build, a frontend build, and a one-click E2E on
`windows-latest` (the platform the renderer and voice stack actually target).

### One-click generation

```
html-video generate "Why local AI matters" --out out
```

| Entry point | Status |
|---|---|
| CLI `generate` | works — real MP4, verified locally |
| Python `create_video()` | works |
| REST `POST /v1/videos` | works, `wait=true` and `wait=false` |
| MCP `create_video` | works |
| Studio Generate page | served by `html-video studio`, wired to the same Runtime |
| **GUI wizard** (PHASE 4) | `html-video start`, or double-click the packaged exe — same Runtime, no terminal |

All of them call `VideoRuntime.create_video()`. None has its own pipeline.

### The narration is real speech, measured

A Chinese request now routes to the installed zh-CN voice rather than to a
placeholder tone (see the two routing defects below). Duration alone cannot tell
those apart — both scale to the estimated narration length — so the check is the
waveform's structure, from `scripts/voice_probe.py`:

```
$ python scripts/voice_probe.py "为什么本地 AI 很重要"
== sapi: available=True languages=['zh-CN', 'en-US']
   wrote sapi.wav: 130290 bytes, 2.95s (text estimates ~1.69s)
   windowed-energy spread (0 = a steady tone): 1.239
== mock_tts: available=True languages=['zh-CN', 'en-US', 'ja-JP']
   wrote mock_tts.wav: 74674 bytes, 1.69s (text estimates ~1.69s)
   windowed-energy spread (0 = a steady tone): 0.014
```

A steady sine scores ~0. SAPI scores 1.239 — syllables, pauses, prosody. Both
numbers are asserted by tests, the second as the control that stops the first
from being able to pass vacuously.

Note the durations: SAPI's output is **1.75× the estimate**. The estimator is
calibrated for the wrong speaking rate, which is why `duration_match` warns — on
mock content the two agree by construction (the mock *uses* the estimate), so the
warning only becomes visible with a real voice. Tracked as a known limitation.

Locally verified one-click, run on 2026-09-15:

```
320×180 · 8.88 s · 240 280 bytes · QC 9 pass / 1 warn (duration_match Δ3.12 s)
providers  mock_llm · mock_tts · advanced_html · srt   fallbacks: none
```

That reference run predates the routing fix, so it shows `mock_tts`; a Chinese
request rendered now routes to `sapi` and carries a real voice.

`--scenes 1` is raised to 4 because `editorial_argument` is a four-beat
structure, and 4 scenes cannot run shorter than ~12 s; the result carries a
warning saying exactly that. See `docs/PHASE3_PRODUCTIZATION_REPORT.md`.

### Real end-to-end render

Produced by `html-video create "…" --preset fast --render` with **real**
providers — no mocks in the output path:

| Item | Value |
|---|---|
| Providers used | `mock_llm` (planner) · `sapi` (TTS) · `legacy_html` (renderer) · `srt` · `ffmpeg` |
| Fallbacks | none — every planned provider succeeded |
| Container | MP4, H.264 1280×720 @ 30 fps + AAC mono |
| Output | 2 192 152 bytes, 26.996 s |
| Quality | 10 checks, 9 pass, 1 warn (`duration_match` Δ4.4 s), 0 fail |
| Artifacts | 4 scene HTML + 4 scene PNG + 4 WAV + 4 segment MP4 + SRT |

Older reference run (different project): 2 524 721 bytes, 33.01 s, 611 886 bit/s.

### Hand-written IR render

`examples/minimal-ir-v2.json` — a 2-scene project with no LLM involved — validates
and renders to a 10.92 s MP4 with QC passing and no fallbacks. Scene-to-scene
frame stability measured at 42–55 dB PSNR, confirming the zoom filter no longer
reshapes the still (it was 10.1 dB before the fix below).

### Hardware profiler (live, this machine)

```
CPU    AMD Ryzen 5 3600 6-Core Processor (12 logical)
RAM    15.9 GB total, 4.3 GB free
GPU    NVIDIA GeForce RTX 2070 — 8192 MB (nvidia-smi)
GPU    GameViewer Virtual Display Adapter — VRAM unknown
GPU    MuMu Virtual Display Adapter — VRAM unknown
Accel  cuda=yes, vulkan=yes, directml=yes, metal=no, rocm_hip=n/a, coreml=n/a
```

### Provider honesty at a glance

| Provider | State | Evidence |
|---|---|---|
| `openai_compatible` | missing credentials | No API key found (`OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `HVW_LLM_API_KEY`). This is the one the wizard's 文案引擎 step configures |
| `mock_llm` | ready | Always available (mock). Tagged `low_fidelity`, so it is never *attached* to the writer — see limitation 1 |
| `sapi` | ready | SAPI available with 2 voices: `Microsoft Huihui Desktop` (zh-CN), `Microsoft Zira Desktop` (en-US) — the languages it advertises are derived from these, not declared |
| `moss` | not installed | Binary not found on PATH: `moss-tts-nano` |
| `aivisspeech` | unavailable | Engine not reachable at `http://127.0.0.1:10101` — the adapter exists, the engine is not running |
| `neural_sidecar` | not installed | `HVW_NEURAL_TTS_URL` is not set — no neural TTS service configured |
| `openai_compatible_tts` | missing credentials | No key found (`HVW_TTS_API_KEY` / `OPENAI_API_KEY`) |
| `mock_tts` | ready | Always available (mock); tagged `low_fidelity`, so it is a last resort rather than a destination |
| `legacy_html` | ready | `msedge` found |
| `advanced_html` | ready | Consumes IR V2 directly; preferred over `legacy_html` |
| `mock_renderer` | ready | Always available (mock) |
| `local_asset` | ready | Filesystem always available |
| `srt` | ready | Pure stdlib writer |

Thirteen registered, none reporting a load failure. No provider reports ready
without a probe that ran, and the four that are unavailable say exactly why.

### Storage

All heavy state is on the data drive: `D:\html-video-workflow`
(venv, cache, projects, outputs, work, logs, npm cache). The repository contains
only source. `HVW_HOME` accepts `/d/x`, `D:\x` and `D:/x` interchangeably.

## Known limitations

These are real and intentional at this phase.

1. **Narration is rule-written unless a key is configured.** With no API key the
   router selects `mock_llm`, which is tagged `low_fidelity` and therefore *not*
   attached to the writer: the words come from the built-in rule templates and
   `narration_source` says `rule`. The composition is real; the prose is
   structural. The wizard states this before the render and again on the result
   page, rather than letting the user discover it in the finished video.
2. **The writing presets only bite when a model is writing.** A preset's system
   prompt is the main thing it does; offline it can only shade the recommended
   template, style, duration and scene count. The UI warns when the user types
   free-form notes while offline.
3. **TTS is SAPI only.** `sapi` is the sole working voice engine, and its
   supported languages come from the voices actually installed — a machine with
   only en-US voices will refuse a zh-CN request rather than read Chinese with
   an English voice. `moss` is registered but reports absent. `mock_tts` writes a
   tone; it can no longer be chosen while a real voice is available, and if it is
   chosen (or explicitly locked in) the plan says so in `warnings`.
4. **`estimate_speech_seconds` underestimates real speech.** Measured at 1.75× on
   SAPI Chinese. `duration_match` therefore warns on real-voice renders. The
   estimator is load-bearing for mock content, so recalibrating it needs care.
5. **One shot per scene.** The IR supports multiple shots; the pipeline renders
   `shots[0]`.
6. **`duration_match` warns.** Narration length and scene duration drift on mock
   content. Expected until a real planner controls pacing.
7. **Duration is a target.** A request the material cannot fill — or that falls
   below the per-scene floor — is reported in `warnings`, never silently
   substituted. See the duration contract in `docs/API.md`.
8. **A language no provider declares leaves TTS unassigned.** A `fr-FR` request
   selects no voice at all. Every refusal is recorded in the routing explanation,
   but unlike the placeholder case it is not yet a first-class warning.
9. **Virtual display adapters appear as GPUs.** `nvidia-smi` is preferred, but
   the CIM fallback also lists virtual adapters with unknown VRAM. They are not
   filtered out because the filter would also hide real secondary GPUs.
10. **Stale `.venv` on C:.** An earlier environment is still on the OS drive
    (~3 400 files). Removal needs user approval because bulk-delete is gated.
11. **The portable build is not code-signed.** Windows SmartScreen warns on first
    run — 更多信息 → 仍要运行. Removing that needs an EV code-signing
    certificate, which the project does not have. The README says so rather than
    letting the user conclude the download is malware.
12. **The frozen exe is verified by build-and-smoke-test, not on a clean VM.**
    `scripts/pack_release.py` builds the zip and `release.yml` runs `doctor` plus
    a real render against the frozen exe. That catches missing bundled data and
    bad path resolution — the failure modes freezing actually produces — but a
    pristine Windows install with neither Python nor FFmpeg on PATH is still a
    manual check.
13. **The GUI is Chinese-only.** The eight presets, the wizard copy and the setup
    checklist are written in Chinese; the request payload and the API are
    language-neutral.

## Fixed during this phase

Each of these was a real defect found by rendering and measuring, not by reading
code. Every one has a regression test.

| Defect | Symptom | Fix |
|---|---|---|
| `zoompan` rescaled stills | Washed-out, blurry text for most of a shot (10.1 dB PSNR between mid-scene frames) | `d=1` + explicit centred `x`/`y`; now ~49 dB |
| **A placeholder voice won the routing** | Chinese narration was a beep while an installed zh-CN voice sat unused; audio QC passed because the tone has the right length | A `low_fidelity` provider can no longer be selected while anything real is usable — a penalty cannot enforce a guarantee. User locks are exempt |
| **The language claim was never verified** | `sapi` declared `zh-CN` on every Windows install, so the router decided on the declaration instead of the installed voices | `Capability.languages` is now the intersection of declared and probed; a contradicted claim is replaced, not emptied (empty would read as "undeclared" and remove the check) |
| **The CLI died reporting a success** | Windows gives a piped stdout the locale encoding; `→` in `--json` routing explanations raised `UnicodeEncodeError` *after* the MP4 was written → exit 1, empty stdout, "pipeline broken" | The stream's failure mode is relaxed, not its encoding — an unencodable glyph degrades, the rest survives (`utils/console.py`) |
| Per-provider voice enumeration spawned a shell per call | Routing one job started dozens of PowerShell processes | Memoised per process. Held at module scope: `@register` replaces the class, so class-level state cannot be referenced by name |
| Project/job id divergence | Manifest in one directory, run artifacts in another | `save_project()` stamps the id onto the caller's object |
| Swallowed import failures | A whole provider domain vanished; 21 test failures, no error | `registry.load_failures()` + error-level logging + `_LOADED` guard |
| `HVW_HOME` accepted relative paths | A literal `\d\html-video-workflow` tree created inside the repo | Normalise `/d/x` → `D:\x`; raise on relative values |
| Probe endpoint POST-only | Studio's plain GET returned no `probe` key | Exposed on GET and POST |
| `to_dict()` dropped derived values | `vram_total_mb` read as `undefined` by the Studio | Derived fields added explicitly |
| `preset` not persisted | A `--preset fast` job read back as `auto` | `create_job()` and `persist()` both carry the preset |

Found during PHASE 4, all with regression tests:

| Defect | Symptom | Fix |
|---|---|---|
| **A configured API key never reached the writer** | The router selected `openai_compatible`, then `PipelinePlanner.__init__` built `ScriptPlanner(llm=None)` — the key was set, the model was chosen, and the narration was still produced by rule templates | `plan()` runs `_route()` **first**, then `_attach_llm()`. A `low_fidelity` planner is deliberately not attached: plausible-looking placeholder JSON is worse than honest rule text |
| **Clearing the key stored it** | The "清除密钥" button reported `cleared: true` and `has_key: true` at the same time — `None` means "leave alone" everywhere in `apply_llm_credentials`, so the clear path was a no-op | Clear is spelled as the empty string, the value that means "set to nothing" |
| **A successful save looked like a failure** | The status echoed the *probe's* `base_url`, which is empty when the endpoint is unreachable, so the field blanked itself and users retyped a URL that had saved correctly | Prefer the probe's answer, fall back to the configured value |
| **The self-check reported a false negative on voice** | `Capability.voices` is only filled by a provider's own `list_voices()`, so reading it in the generic path said "no Chinese voice" on a machine that has one — sending the user to install a language pack they already had | The checklist asks the provider directly |
| **The async result was thinner than the synchronous one** | `POST /v1/videos?wait=false` polled back with template, style, title, scene count and provenance all empty — a broken-looking result page rather than a slow one | `create_video` records the product facts on `job.plan` before the run; `job_result()` reconstructs the full `VideoResult` |
| **Provenance lived only on the return value** | `PipelinePlan.writing_preset`/`narration_source` were never set, so anything reading the plan rather than the result saw nothing | `build_script()` writes both onto the plan as soon as they are knowable |
| **A saved key deleted every provider** | `reload_providers()` cleared the registry and re-imported the builtin modules. Python caches modules in `sys.modules`, so the `@register` decorators never ran again: the registry came back **empty**, and `load_failures()` was empty too. The whole product lost every provider at the exact moment it told the user their key had been accepted | Rebuild by re-instantiating the registered **classes** (`rebuild_instances()`); `clear()` no longer forgets them, and the reload logs if the count drops |
| **A Chinese-locale Windows killed the packaged render** | Windows gives a child's pipe the *locale* codec — `gbk` on a zh-CN box — while ffmpeg and ffprobe write UTF-8. The decode failed inside `Popen._readerthread`, a background thread, so the `UnicodeDecodeError` was swallowed: `communicate()` returned `None` and the caller saw `returncode == 0` with no stdout. The MP4 was composed and written, then the run died on `json.loads(None)` — a `TypeError` pointing at the wrong line | `errors="replace"` on every text subprocess call in `src/`. A mis-decoded glyph now degrades into a replacement character, which can only affect a log line. Guarded by an AST test, because the next `subprocess.run` will not be written with code pages in mind |
| **The CLI advertised a command the parser rejected** | The README's bare `html-video` line only worked because `main()` branched around `parse_args`; `build_parser().parse_args([])` raised | `set_defaults(command="start", func=cmd_start)` on the parser, with the serve flags accepted at the top level so `html-video --port 8899` parses too |
| **`pack_release.py` could not build locally** | Vite empties its out dir with a bulk `rmSync`, which a guarded sandbox refuses; the build died with a confusing message | The script clears from Python and degrades to an in-place overwrite when a delete is refused, instead of aborting |
| **The zip would have shipped a package manager's shim** | CI installs ffmpeg through Chocolatey, whose `bin\ffmpeg.exe` is a small *proxy* that names the real binary by absolute path. It is an ordinary file, so `resolve()` returned it unchanged and the copy ran happily — on the build machine, where that path exists. The workflow's own smoke test would have passed, and the published zip would have failed on the user's very first render, with an error pointing at the app rather than at the download | Size is the tell (a real ffmpeg is tens of MB, a shim is tens of KB) and the `.shim` descriptor is the remedy, so the directory is followed to the real binary. What lands in `bin/` is then measured, not assumed, and a build that cannot find real tools **fails** instead of warning — "nothing else to install" is the whole promise of the download |

## Not implemented

Deliberately absent; each needs a decision record before it is added.

- Avatar providers, image/video/music providers
- Model download/management (`html-video models pull`). There is still no
  download path at all, which is *why* first run needs nothing
- **A neural voice that is actually installed.** The adapters exist —
  `aivisspeech` (local engine), `neural_sidecar` (a service behind
  `HVW_NEURAL_TTS_URL`) and `openai_compatible_tts` (a hosted endpoint) — and all
  three probe honestly as unavailable or unconfigured on this machine. So the
  product ships with exactly one working voice engine, `sapi`
- Cloud services, accounts, login, payments, marketplace
- Timeline editor
- Consuming `VisualDesignCritic` findings to change a layout
- Code signing for the Windows build (SmartScreen warns on first run)

## Packaging

`scripts/pack_release.py` → `dist/release/html-video-windows-x64-<version>.zip`
(185 MB, of which 424 MB uncompressed is the bundled `ffmpeg.exe` + `ffprobe.exe`).
Built from `packaging/html-video.spec`; frozen path resolution is
`config/paths.py::bin_dir()`, and `ffmpeg/service.py::_find_tool` prefers
`bin/` over `PATH` so a machine with an old system ffmpeg cannot change what the
product does.

Verified on the frozen bundle, not inferred from the source run:

| Check | Result |
|---|---|
| `html-video.exe doctor` | exit 0, 13 providers, no load failures |
| bundled ffmpeg precedence | with `PATH` stripped of ffmpeg, `doctor` still reports both tools — it found them in `bin/` |
| a real render | 51.7 s, 320×180, `QC PASS`, identical to the source run including its single `duration_match` warning |
| `studio` serving | `/` returns the shell *and* its asset bundle; `/v1/setup/status` `ready: true`; `/v1/presets` 8; `/v1/outputs` lists the render |
| path containment | `POST /v1/desktop/reveal` with `C:\Windows\System32` → **403** |
| what `bin/` contains | `resolve_tool` follows the real WinGet `Links\ffmpeg.EXE` reparse point to `…\Gyan.FFmpeg_…\bin\ffmpeg.exe` (212 MB). A Chocolatey-style `ffmpeg.exe.shim` and a Scoop-style `ffmpeg.shim` resolve the same way; a proxy with no usable descriptor resolves to *nothing*, which fails the build |

`.github/workflows/release.yml` repeats the same smoke test in CI before
publishing, and creates the GitHub Release on a `v*` tag. A release asset that
fails on first run is worse than no release: it is the first thing a new user
meets, and they will not file a bug — they will close the tab. The workflow also
measures the bundled tools directly, because the smoke test alone cannot tell a
shim from the real thing.
