# Roadmap

Ordered by dependency, not by ambition. Each phase must leave the repository in a
state where `pytest` is green and a video can still be rendered.

Legend: **DONE** · **NEXT** · **LATER** · **OUT OF SCOPE** (this cycle)

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
- `doctor`, `providers`, `benchmark`, `validate`, `projects`, `create`, `render`,
  `status`, `gallery`, `serve`, `settings`
- Studio: Dashboard, New Project, Projects, Providers, Hardware, Settings
- 74 tests green; verified H.264 + AAC MP4 produced by real providers

## Phase 1 — Real local synthesis · **NEXT**

Replace the mock defaults with genuine local capability, without adding a
download step to first run.

- Add a recommended local TTS provider behind the existing `TTSProvider`
  interface; keep `sapi` as the always-works fallback and `mock_tts` as the last
  resort
- Benchmarked model acquisition: explicit `html-video models pull <id>` command,
  resumable downloads, checksum verification, sizes shown *before* download
- Registry-aware model storage under `models_dir()`; never auto-download during a
  render job
- Voice catalogue with real `VoiceInfo` (language, gender, styles) from probe
- Cache-aware prosody: markup produced by the IR is honoured by at least one
  non-SAPI engine

## Phase 2 — Renderer depth · **NEXT**

- `advanced_html` renderer: true multi-layer motion driven by `motion.semantic`,
  rather than the current CSS keyframe approximation
- A real timeline: sequences with multiple shots per scene
- Deterministic frame mode for stills that must match exactly across machines
- Font subsetting so CJK renders identically on a machine without the fonts

## Phase 3 — Quality and observability · **LATER**

- Perceptual QC: SSIM between consecutive frames to catch stutter
- Loudness compliance report persisted per job, not just pass/fail
- Artifact provenance UI: which provider produced which frame, and with what config
- Cost and time accounting per provider, feeding the ranker as real benchmarks

## Phase 4 — Avatar and image providers · **LATER**

Only after the renderer is genuinely good, because an avatar on top of a weak
composition is still a weak composition.

- `AvatarProvider` implementations isolated behind `subprocess` or `http` mode
- Explicit VRAM admission checks before a job starts, not a crash mid-render
- Graceful degradation to an audio-only track when VRAM is insufficient

## Phase 5 — Distribution · **LATER**

- Provider entry points so third parties can ship providers without forking
- A curated provider index with licence metadata surfaced in the Studio
- Template packs separate from the core IR

## Explicitly out of scope

These are deliberately excluded, not forgotten. Adding any of them requires a
decision record in `DECISIONS.md` first.

- **OUT OF SCOPE** Cloud rendering or a hosted service
- **OUT OF SCOPE** Accounts, login, payments, marketplace
- **OUT OF SCOPE** A full NLE-grade timeline editor
- **OUT OF SCOPE** Bulk rewriting of the ten legacy templates
- **OUT OF SCOPE** Node/Electron desktop packaging
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
