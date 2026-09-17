# Roadmap

Ordered by dependency, not by ambition. Each phase must leave the repository in a
state where `pytest` is green and a video can still be rendered.

Legend: **DONE** · **PARTIAL** · **NEXT** · **LATER** · **OUT OF SCOPE** (this cycle)

---

## Phase 0 — Foundation · **DONE**

The architectural skeleton, with one real end-to-end path through it.

- App boots (`html-video` CLI, `create_app()` REST API, Studio SPA)
- Layered config with masked secrets, `.env` support, `HVW_*` env overrides
- Video Project IR V2 + V1→V2 migration (lossless, idempotent)
- Provider contract: `ProviderSpec` / `ProbeResult` / `Capability` + typed errors
- Provider registry with builtin discovery and honest `load_failures()` reporting
- Job/Task/Step/Artifact runtime, append-only `events.jsonl`, cancel support
- Content-addressed cache keyed on content + provider + config hash
- Hardware profiler with live probes and no hardcoded machine facts
- Capability resolver, provider ranker, pipeline planner with explainable reasons
- Quality engine: 10 real ffprobe/ffmpeg checks
- Legacy adapter wrapping the untouched `scripts/workflow.py`

## Phase 1 — Real local synthesis · **PARTIAL**

- **DONE** A real local TTS provider behind the existing interface — `sapi`,
  probed rather than declared: its supported languages are the intersection of
  what it claims and what `GetInstalledVoices()` actually lists
- **DONE** Voice catalogue with real `VoiceInfo` from probe
- **NEXT** A non-SAPI engine. `moss` is registered but reports absent; nothing
  neural ships yet
- **NEXT** Benchmarked model acquisition: `html-video models pull <id>`,
  resumable downloads, checksum verification, sizes shown *before* download.
  Still no download path at all — which is why first run needs nothing
- **LATER** Cache-aware prosody honoured by a non-SAPI engine

## Phase 2 — Renderer depth · **PARTIAL**

- **DONE** `advanced_html`: renders IR V2 directly via `SceneCompiler` — 9 motion
  presets, 9 layouts, safe areas per platform, a type system, and a design critic.
  The router prefers it over `legacy_html`
- **NEXT** Consuming the critic's findings. It reports; nothing acts on the report
- **NEXT** The motion chooser never reaches `parallax`/`drift`:
  `SceneVariationPolicy` only rotates layouts, so `AA-012` ("nothing moves
  continuously") fires on every scene rendered
- **NEXT** A real timeline: sequences with multiple shots per scene
- **LATER** Deterministic frame mode for stills that must match across machines
- **LATER** Font subsetting so CJK renders identically without the fonts installed

## Phase 3 — One-click productization · **DONE**

One request in, one MP4 out, from every entry point, with the decisions attached.

- **DONE** `VideoRuntime.create_video()` as the single implementation behind CLI,
  Python SDK, REST, MCP and Studio
- **DONE** `--out <dir>`, honest failure codes, `reasons` / `warnings` / `fallbacks`
- **DONE** The routing defects that made a real voice lose to a placeholder, and
  made the CLI exit 1 *after* writing the MP4
- **DONE** Deployment: wheel + prebuilt Studio served from one process

See `docs/PHASE3_PRODUCTIZATION_REPORT.md`.

## Phase 4 — Non-technical GUI + portable release · **DONE**

The Phase 3 product still assumed a terminal. This phase removes that assumption.

- **DONE** A seven-step Chinese wizard (`apps/studio/src/wizard/`): environment
  self-check, narration engine, topic, writing style, template and colour,
  generation, finished file
- **DONE** Eight **writing presets** — a third concept, orthogonal to templates
  and styles, that briefs the model and shades the defaults non-destructively
- **DONE** Optional API key: saved, hot-reloaded, *and probed*; clearing works;
  the UI states plainly what running offline costs
- **DONE** `我的作品` gallery with inline playback, reveal-in-Explorer and open
- **DONE** Portable Windows build: PyInstaller spec, `scripts/pack_release.py`,
  bundled FFmpeg, `使用说明.txt`, and `release.yml` publishing the zip on a `v*` tag
- **DONE** Documentation rewritten for people who do not read code

See `CURRENT_STATUS.md` § PHASE 4.

## Phase 5 — Model management and a second engine · **NEXT**

The clearest remaining gap: there is exactly one working voice engine and no way
to install a better one.

- `html-video models pull <id>` with resumable, checksummed downloads
- Sizes, licences and disk cost shown before anything is fetched
- Registry-aware storage under `models_dir()`; never auto-download during a render
- A second TTS engine behind the existing interface, replacing the absent `moss`
- Recalibrate `estimate_speech_seconds` against real speech (currently 1.75× low),
  with the mock path held fixed

## Phase 6 — Quality and observability · **LATER**

- Perceptual QC: SSIM between consecutive frames to catch stutter
- Loudness compliance report persisted per job, not just pass/fail
- Artifact provenance UI: which provider produced which frame, and with what config
- Cost and time accounting per provider, feeding the ranker as real benchmarks

## Phase 7 — Avatar and image providers · **LATER**

Only after the renderer is genuinely good, because an avatar on top of a weak
composition is still a weak composition.

- `AvatarProvider` implementations isolated behind `subprocess` or `http` mode
- Explicit VRAM admission checks before a job starts, not a crash mid-render
- Graceful degradation to an audio-only track when VRAM is insufficient

## Phase 8 — Distribution · **LATER**

- Provider entry points so third parties can ship providers without forking
- A curated provider index with licence metadata surfaced in the GUI
- Template packs separate from the core IR
- Code signing for the Windows build, so SmartScreen stops warning on first run

## Explicitly out of scope

These are deliberately excluded, not forgotten. Adding any of them requires a
decision record in `DECISIONS.md` first.

- **OUT OF SCOPE** Cloud rendering or a hosted service
- **OUT OF SCOPE** Accounts, login, payments, marketplace
- **OUT OF SCOPE** A full NLE-grade timeline editor
- **OUT OF SCOPE** Bulk rewriting of the ten legacy templates
- **OUT OF SCOPE** Electron / Node desktop packaging. The Windows build is a
  PyInstaller one-dir freeze plus a bundled FFmpeg — a zip, not an installer, and
  no second toolchain for the user to install
- **OUT OF SCOPE** Auto-installing 10 GB+ model weights on first launch

## Standing constraints

These hold in every phase:

1. `scripts/workflow.py`, `scripts/sapi_tts.ps1` and `agents/openai.yaml` stay
   byte-identical. They are the compatibility surface for existing users.
2. No `Ready` / `Available` / `Success` state without a probe that actually ran.
3. No silent degradation: every provider substitution is recorded in the job
   manifest.
4. Tests must not download models or call a paid API.
5. Heavy artifacts live outside the repository, on the data drive when one exists.
6. A packaged build must never claim a capability the unpackaged one does not have
   — the frozen exe runs the same probes.
