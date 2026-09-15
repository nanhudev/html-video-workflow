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
pytest tests             → all passed, 0 failures, 0 errors, 0 skipped
npm run typecheck        → clean
npm run build            → built
python scripts/export_schema.py --check  → OK (schema matches models)
```

Read the count from the junit report (`--junitxml`), not the console: this
runner kills long-lived child processes, so a console summary line is not
trustworthy here. The full run takes ~14 minutes.

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

All five call `VideoRuntime.create_video()`. None has its own pipeline.

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
| `openai_compatible` | missing credentials | No API key found |
| `mock_llm` | ready | Always available (mock) |
| `sapi` | ready | SAPI available with 2 voices: `Microsoft Huihui Desktop` (zh-CN), `Microsoft Zira Desktop` (en-US) — the languages it advertises are derived from these, not declared |
| `moss` | not installed | Binary not found on PATH: `moss-tts-nano` |
| `mock_tts` | ready | Always available (mock); tagged `low_fidelity`, so it is a last resort rather than a destination |
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
2. **TTS is SAPI only.** `sapi` is the sole working voice engine, and its
   supported languages come from the voices actually installed — a machine with
   only en-US voices will refuse a zh-CN request rather than read Chinese with
   an English voice. `moss` is registered but reports absent. `mock_tts` writes a
   tone; it can no longer be chosen while a real voice is available, and if it is
   chosen (or explicitly locked in) the plan says so in `warnings`.
3. **`estimate_speech_seconds` underestimates real speech.** Measured at 1.75× on
   SAPI Chinese. `duration_match` therefore warns on real-voice renders. The
   estimator is load-bearing for mock content, so recalibrating it needs care.
4. **One shot per scene.** The IR supports multiple shots; the pipeline renders
   `shots[0]`.
5. **`duration_match` warns.** Narration length and scene duration drift on mock
   content. Expected until a real planner controls pacing.
6. **Duration is a target.** A request the material cannot fill — or that falls
   below the per-scene floor — is reported in `warnings`, never silently
   substituted. See the duration contract in `docs/API.md`.
7. **A language no provider declares leaves TTS unassigned.** A `fr-FR` request
   selects no voice at all. Every refusal is recorded in the routing explanation,
   but unlike the placeholder case it is not yet a first-class warning.
8. **Virtual display adapters appear as GPUs.** `nvidia-smi` is preferred, but
   the CIM fallback also lists virtual adapters with unknown VRAM. They are not
   filtered out because the filter would also hide real secondary GPUs.
9. **Stale `.venv` on C:.** An earlier environment is still on the OS drive
   (~3 400 files). Removal needs user approval because bulk-delete is gated.

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

## Not implemented

Deliberately absent; each needs a decision record before it is added.

- Avatar providers, image/video/music providers
- Model download/management (`html-video models pull`)
- Neural TTS beyond SAPI/MOSS
- Cloud services, accounts, login, payments, marketplace
- Timeline editor
- Consuming `VisualDesignCritic` findings to change a layout
