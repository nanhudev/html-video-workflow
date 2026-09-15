# Current Status

**Version:** 0.3.0 · **Phase:** One-click productization (PHASE 3) ·
**Last verified:** 2026-09-15 · **Branch:** `phase3-productization`

One prompt in, one MP4 out, through four entry points that share one
implementation. See `docs/PHASE3_PRODUCTIZATION_REPORT.md` for the full account
and `docs/API.md` for the contract.

This file is a snapshot, not a plan. For direction see `ROADMAP.md`; for the
reasons behind the architecture see `DECISIONS.md`.

---

## Verified working

Everything below was executed on the development machine, not inferred from code.

### Test suite

```
pytest tests             → 324 passed, 0 failures, 0 errors, 0 skipped
npm run typecheck        → clean
npm run build            → built
python scripts/export_schema.py --check  → OK (schema matches models)
```

Read the count from the junit report (`--junitxml`), not the console: this
runner kills long-lived child processes, so a console summary line is not
trustworthy here. The full run takes ~12 minutes.

CI is the authority. `.github/workflows/ci.yml` runs one job per test file on
ubuntu, plus a package build, a frontend build, and a one-click E2E on
`windows-latest` (the platform the renderer and voice stack actually target).

### One-click generation

```
html-video generate "Why local AI matters" -o result.mp4
```

| Entry point | Status |
|---|---|
| CLI `generate` | works — real MP4, verified locally and in CI |
| Python `create_video()` | works |
| REST `POST /v1/videos` | works, `wait=true` and `wait=false` |
| MCP `create_video` | works |
| Studio Generate page | wired to the same Runtime |

All five call `VideoRuntime.create_video()`. None has its own pipeline.

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
| `openai_compatible` | missing credentials | No API key found |
| `mock_llm` | ready | Always available (mock) |
| `sapi` | ready | SAPI available with 2 voices |
| `moss` | not installed | Binary not found on PATH: `moss-tts-nano` |
| `mock_tts` | ready | Always available (mock) |
| `legacy_html` | ready | `msedge` found |
| `advanced_html` | ready | Consumes IR V2 directly; preferred over `legacy_html` |
| `mock_renderer` | ready | Always available (mock) |
| `local_asset` | ready | Filesystem always available |
| `srt` | ready | Pure stdlib writer |

No provider reports ready without a probe that ran.

### Storage

All heavy state is on the data drive: `D:\html-video-workflow`
(venv, cache, projects, outputs, work, logs, npm cache). The repository contains
only source. `HVW_HOME` accepts `/d/x`, `D:\x` and `D:/x` interchangeably.

## Known limitations

These are real and intentional at this phase.

1. **Mock planners by default.** Without an API key, `mock_llm` produces
   structured placeholder content. The composition is real; the words are not.
2. **TTS is SAPI only.** `sapi` is the sole working voice engine; `moss` is
   registered but reports absent. `mock_tts` writes a tone, and says so in its
   `message`, so it can never be mistaken for speech.
3. **One shot per scene.** The IR supports multiple shots; the pipeline renders
   `shots[0]`.
4. **`duration_match` warns.** Narration length and scene duration drift on mock
   content. Expected until a real planner controls pacing.
5. **Duration is a target.** A request the material cannot fill — or that falls
   below the per-scene floor — is reported in `warnings`, never silently
   substituted. See the duration contract in `docs/API.md`.
6. **Virtual display adapters appear as GPUs.** `nvidia-smi` is preferred, but
   the CIM fallback also lists virtual adapters with unknown VRAM. They are not
   filtered out because the filter would also hide real secondary GPUs.
7. **Stale `.venv` on C:.** An earlier environment is still on the OS drive
   (~3 400 files). `D:\html-video-workflow\venv` is the live one. Removal needs
   user approval because bulk-delete is gated.

## Fixed during this phase

Each of these was a real defect found by rendering and measuring, not by reading
code. Every one has a regression test.

| Defect | Symptom | Fix |
|---|---|---|
| `zoompan` rescaled stills | Washed-out, blurry text for most of a shot (10.1 dB PSNR between mid-scene frames) | `d=1` + explicit centred `x`/`y`; now ~49 dB |
| Project/job id divergence | Manifest in one directory, run artifacts in another | `save_project()` stamps the id onto the caller's object |
| Swallowed import failures | A whole provider domain vanished; 21 test failures, no error | `registry.load_failures()` + error-level logging + `_LOADED` guard |
| `HVW_HOME` accepted relative paths | A literal `\d\html-video-workflow` tree created inside the repo | Normalise `/d/x` → `D:\x`; raise on relative values |
| Probe endpoint POST-only | Studio's plain GET returned no `probe` key | Exposed on GET and POST |
| `to_dict()` dropped derived values | `vram_total_mb` read as `undefined` by the Studio | Derived fields added explicitly |
| `preset` not persisted | A `--preset fast` job read back as `auto` | `create_job()` and `persist()` both carry the preset |

## Not implemented

Deliberately absent; each needs a decision record before it is added.

- Avatar providers, image/video/music providers
- Model download/management (`html-video models pull`)
- Neural TTS beyond SAPI/MOSS
- Cloud services, accounts, login, payments, marketplace
- Timeline editor
- Consuming `VisualDesignCritic` findings to change a layout
