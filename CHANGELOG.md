# Changelog

Notable changes, newest first. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semantic
versioning.

## [Unreleased]

## [0.5.0]

### Fixed

- **Video length now matches the requested duration.** A 28-second request
  produced a 20.3-second video. Two independent causes: the planner budgeted
  0.9 s of tail padding per scene while the composer added 0.35 s, and the
  composer passed `-shortest` to FFmpeg, which made the *audio* — not the
  requested duration — the authority on segment length. Both stages now read one
  constant, and `-shortest` is gone from segment encoding. Verified: 28 s
  requested, 28.4 s delivered, no narration trimmed.
- **On-screen text is no longer cut mid-word.** The scene headline used a bare
  `text[:28]` slice and the body copy appended an ellipsis at a character count,
  so the largest text on screen regularly ended inside a word
  ("……去往别人的"). Both now break on a clause boundary, and an unbreakable
  run is marked with an ellipsis instead of being silently truncated.
- **Narration is no longer trimmed for a rounding error.** Trimming was driven
  by a per-scene quota averaged across all scenes, so a 0.37 s surplus cost two
  sentences their last four characters. Each scene now gives up only what it is
  itself over, and a scene close to its budget keeps its words.
- **The CLI is reachable without an installed console script.** `html-video`
  lives in whichever environment was installed last, and a half-uninstalled
  virtualenv can leave the script on disk while the package it imports is gone —
  which reported `ModuleNotFoundError` and blamed the project for local damage.
  `python -m html_video_workflow.cli` now works, and both `scripts/dev.py` and
  `scripts/e2e_one_click.py` take the console script only when it actually runs.
- **A diagnostic can no longer be killed by its own output.** The one-click
  end-to-end check read subprocess output with the console's locale encoding, so
  a Chinese error message from a provider raised `UnicodeDecodeError` while
  reporting — a diagnosable failure becoming an unexplained one. Subprocess
  output is read as UTF-8 with a relaxed failure mode.
- **The Windows release build failed with no diagnosable output.** `pack_release`
  ran subprocesses through `shell=True`, which joins a command list unquoted; a
  path containing a space truncated the command, and the child's explanation
  arrived in an OEM codepage the CI runner rendered as `????`. Subprocesses now
  run without a shell, and both stdout and stderr are surfaced with the exit code.
  PyInstaller also runs at `--log-level INFO` (it was `WARN`, which hid the
  reason for the failure).
- **…and then failed again on Chocolatey's shim.** The release runner handed the
  build `Get-Command ffmpeg.exe`, which is Chocolatey's proxy — correctly
  refused, since a shim only works on the machine that made it. The workflow now
  finds the real binary under the package directory and prints its size.
- **…and then failed again, for want of four characters.** With the shell gone,
  `["npm", "ci"]` reached `CreateProcess` directly, which does not apply
  `PATHEXT` — npm on Windows is `npm.cmd`, so the build raised
  `FileNotFoundError` and reported only `exit code 1`. npm is now resolved with
  `shutil.which` (which does apply `PATHEXT`) instead of being named.

### Added

- `docs/STATUS.md` — the single authoritative statement of what is stable,
  experimental and missing.
- `docs/examples/` — three real outputs with their configs and measured numbers.
- `docs/assets/demo.gif` and `docs/assets/demo.mp4` — a real 28-second render.
- `scripts/measure_speech_rate.py` — re-measure the installed voice's speaking
  rate instead of trusting the constant.
- `python -m html_video_workflow.cli` — the console script without the
  installation, for source checkouts and half-uninstalled environments.
- Regression tests pinning the speech estimator to real SAPI timings, the
  planner/composer padding contract, and the no-truncated-words rule.

### Changed

- Root directory reduced to the files a reader needs; development and historical
  documents moved to `docs/development/` and `docs/history/`.
- README rewritten as a product page: what it does, a watchable demo, a short
  quick start, and an explicit statement that offline narration is
  template-written rather than model-written.
- Speaking-rate calibration corrected from an assumed 5.2 CJK chars/sec to the
  measured 3.35, and the seven templates' pacing hints re-derived from it.

## [0.4.0]

### Added

- Seven-step GUI wizard and a "My Videos" page for non-technical users.
- Portable Windows build: PyInstaller one-dir bundle with FFmpeg and FFprobe
  included, plus the release workflow that publishes it.
- Setup API (`/v1/setup/status`, `/v1/setup/llm`, `/v1/setup/llm/test`) and
  desktop integration (`reveal`, `open`).
- Eight writing presets.

### Fixed

- Configuring an API key selected the provider but the planner still built its
  writer with `llm=None`, so narration stayed rule-written. The router now runs
  before the writer is attached.

## [0.3.0]

### Added

- `VideoRuntime.create_video()` as the single implementation behind the CLI,
  Python SDK, REST API and MCP server.
- Hardware profiling and capability-based provider routing.
- `advanced_html` renderer: nine layout primitives, nine motion presets, safe
  areas, and a visual critic.

## Earlier

Foundation, the HTML/CSS template renderer, SAPI TTS, FFmpeg composition and the
original project-JSON workflow. See
[`docs/history/FOUNDATION_REPORT.md`](docs/history/FOUNDATION_REPORT.md).
