# Foundation Report

**Phase:** Architecture Foundation / Framework Scaffold
**Status:** COMPLETE
**Date:** 2026-09-15
**Home directory (verified):** `D:\html-video-workflow`

This report describes what was built, what was actually verified on a real machine,
what is not yet built, and what a successor should do next. Every claim below was
measured, not assumed. Where something does not work, it is stated plainly.

---

## FOUNDATION STATUS

**COMPLETE.** All twelve deliverables required by this phase exist, import cleanly, and
are exercised by the test suite.

| # | Deliverable | State | Evidence |
| --- | --- | --- | --- |
| 1 | App boot | Done | `html-video --help`, console entry point installed |
| 2 | Config layer | Done | Layered resolution + secret masking, covered by tests |
| 3 | Schemas | Done | `schemas/video_ir_v2.schema.json` generated from the models, `--check` clean |
| 4 | Hardware profiler | Done | Live probe of this machine — see below |
| 5 | Provider interface | Done | `ProviderSpec` / `ProbeResult` / typed errors |
| 6 | Provider registry | Done | 9 providers discovered, load failures are now visible |
| 7 | Runtime | Done | `Job ▸ Task ▸ Step ▸ Artifact`, manifests persisted |
| 8 | Project IR V2 | Done | Renderer-neutral; validates and renders |
| 9 | Legacy adapter | Done | Original workflow still runs end to end |
| 10 | REST API | Done | FastAPI app, `/health`, `/system/*`, `/providers/*`, jobs |
| 11 | Studio UI | Done | Typecheck and production build both clean |
| 12 | doctor + smoke test | Done | Real machine report; full E2E smoke test passes |

### Constraints honoured

This phase was explicitly a scaffold. None of the following were done, by design:

- No model downloads. No 50 GB of weights. `D:\html-video-workflow\models` exists but is empty.
- No TTS engines wired beyond what already worked (`sapi`, plus the `mock` provider).
- No MuseTalk / LivePortrait / ComfyUI integration.
- No cloud services, accounts, login, or payment.
- No marketplace.
- No timeline editor.
- No large-scale template redesign — the ten existing templates are untouched.

---

## LEGACY COMPATIBILITY

**Preserved and verified.** The original project is not rewritten; the new layer sits
beside it.

Untouched, as required:

- `scripts/workflow.py`
- `scripts/sapi_tts.ps1`
- `agents/openai.yaml`

The legacy workflow — structured JSON → HTML/CSS → local TTS → FFmpeg — still runs.
The legacy JSON project format is still accepted and is translated into IR V2 through
an adapter rather than being replaced, so existing user projects keep working.

The ten original HTML/CSS templates are unchanged and are still what the
`legacy_html` renderer drives.

`tests/test_legacy_compat.py` asserts this boundary holds, so a future change cannot
silently break the old path.

---

## ARCHITECTURE

The layering, from the design document:

```
Agent decides  →  IR describes  →  Provider executes
                      ↓
              Runtime schedules
                      ↓
         Studio visualises  ·  Quality system verifies
```

### Layers

| Layer | Module | Responsibility |
| --- | --- | --- |
| Config | `config/` | Layered settings, path resolution, secret masking |
| Hardware | `hardware/` | Live machine probing, no hardcoded facts |
| Project IR | `project/` | IR V2 models, validation, store, legacy adapter |
| Providers | `providers/` | Spec/probe/capability, registry, isolation |
| Routing | `pipeline/` | Capability resolution, ranking, pipeline planning |
| Runtime | `runtime/` | Job/Task/Step/Artifact, events, cache |
| Media | `ffmpeg/`, `tts/` | Composition and speech |
| API | `api/` | REST surface |
| Studio | `studio/` | Local UI |

### The central design rule

**A layer may not reach past the one below it, and no layer may name a renderer.**

The IR is the clearest expression of this. A layer is
`{type, role, content, layout, motion}`. It must never contain `remotionComponent` or
`cssClass` — not because those strings are banned, but because the moment they appear,
the project model has become a wrapper around one renderer and can no longer be
retargeted. `tests/test_project_ir.py` enforces this.

### Provider model: claim vs. check

This is the single most important idea in the foundation, and it exists to make faking
success structurally difficult:

- **`ProviderSpec`** is a *claim*. It says what the provider can do if everything is
  present. It is static data.
- **`ProbeResult`** is a *check*. It runs against the live machine and returns what is
  actually true right now.
- **`Capability`** is the *resolved truth*. A probe may **confirm** a spec or
  **downgrade** it. A probe may never upgrade a spec.

Nothing in the system reports `Ready` or `Available` on the strength of a spec alone.

### Provider isolation

Providers declare an isolation mode — `inprocess`, `subprocess`, `http`, or `api` — and
heavy imports are deferred out of module import time. This is why the registry can
enumerate nine providers, including ones for engines that are not installed, without
paying their import cost or crashing when they are absent.

### Fallbacks are recorded, never silent

Fallback chains are declared:

```
tts:      [fish_speech, cosyvoice, moss, sapi, mock_tts]
renderer: [advanced_html, legacy_html, mock_renderer]
llm:      [openai_compatible, mock_llm]
subtitle: [srt]
```

Every substitution is written into `job.fallbacks`. A render that quietly dropped from
a real engine to a mock is a lie, so the runtime refuses to allow it to be a quiet one.

Full detail: [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## STUDIO STATUS

**Builds clean; functional for inspection.**

```
npm run typecheck   → clean
npm run build       → 164.94 kB JS / 3.99 kB CSS
```

The Studio provides local views for jobs, providers, hardware profile, and quality
reports. It is a *read and trigger* surface — deliberately not a timeline editor, which
is out of scope for this phase.

It talks to the same REST API as everything else; it holds no privileged access.

---

## RUNTIME STATUS

**Working.**

- Model: `Job ▸ Task ▸ Step ▸ Artifact`
- Statuses: `queued | planning | running | paused | failed | completed | cancelled`
- Manifests persisted as `job.json` alongside the job's artifacts
- Append-only `events.jsonl` per job, consumed in-process for SSE
- Content-addressed caching: cache key = content + provider id + config hash; index at
  `<home>/cache/index.json`

### Cache verification

`scripts/dev.py clean -y` cleared **39** cached entries and the next run repopulated
them, confirming the cache is a real, disposable accelerator rather than a hidden
source of truth.

---

## PROVIDER STATUS

Nine providers registered. Status below is from `doctor` on this machine — the `??` and
`--` marks are the honest output, not decoration.

| Type | Provider | State | Real probe result |
| --- | --- | --- | --- |
| llm | `openai_compatible` | `??` unavailable | No API key found (`OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `HVW_LLM_*`) |
| llm | `mock_llm` | `OK` | Always available (mock) |
| tts | `sapi` | `OK` | SAPI available with **2 voices** |
| tts | `moss` | `--` not installed | Binary not found on PATH: `moss-tts-nano` |
| tts | `mock_tts` | `OK` | Always available (mock) |
| renderer | `legacy_html` | `OK` | Browser found: `msedge` @ `C:\Program Files (x86)\Microsoft\Edge\...` |
| renderer | `mock_renderer` | `OK` | Always available (mock) |
| asset | `local_asset` | `OK` | Filesystem always available |
| subtitle | `srt` | `OK` | Pure stdlib writer |

Legend: `OK` = probed and working · `??` = installed but unusable (e.g. missing
credentials) · `--` = not installed.

Note that `moss` reports `--` rather than a failure. A TTS engine that is simply absent
is not an error condition; it is a routing input.

Providers declared in the spec for future phases but **not** implemented here:
`fish_speech`, `cosyvoice`, `advanced_html`, and the avatar / image / video / music /
asr families. They are referenced by fallback chains and ranking tables but have no
working implementation, so they never appear as `OK`.

---

## HARDWARE PROFILER STATUS

**Working, and it reports what it actually finds.**

Verbatim output on this machine:

```
OS            Windows 10.0.22631 (AMD64)
CPU           AMD Ryzen 5 3600 6-Core Processor (12 logical)
RAM           15.9 GB total, 2.5 GB free
GPU           NVIDIA GeForce RTX 2070 — 8192 MB
GPU           GameViewer Virtual Display Adapter — VRAM unknown
GPU           MuMu Virtual Display Adapter — VRAM unknown
Accel         cuda=yes, rocm_hip=n/a, vulkan=yes, directml=yes, metal=no, coreml=n/a
```

### Method, and why it matters

- `nvidia-smi` is preferred because it reports **accurate VRAM**.
- PowerShell CIM is the fallback, but it is treated with suspicion: it yields names
  only, and its `AdapterRAM` field is a signed 32-bit integer, so any card with 4 GB or
  more reports a wrong value. The profiler therefore does not trust `AdapterRAM`.
- `lspci` is used on Linux; `system_profiler` on macOS.

**No machine facts are hardcoded.** The three GPUs above — including two virtual display
adapters that the profiler cannot size — are discovered, not assumed. Virtual adapters
correctly report `VRAM unknown` rather than a fabricated number.

---

## TEST STATUS

```
75 passed
```

Schema drift check:

```
OK   schemas\video_ir_v2.schema.json matches the models
```

Studio:

```
npm run typecheck   → clean
npm run build       → clean
```

The suite covers config, hardware profiling, IR validation, the legacy adapter, the
provider registry and probe semantics, routing and rejection reasons, the runtime and
job manifests, the REST API, and a full end-to-end smoke render.

Two regression tests are worth calling out because they were written to fail against
the bug they guard:

- `test_gentle_push_in_does_not_rescale_the_still` — asserts PSNR > 35 dB between two
  frames of a still shot. It was **verified to fail at 10.1 dB** when the defect was
  reinstated, then to pass once fixed.
- `test_render_stage_falls_back_when_browser_missing` — exercises a genuine mid-run
  fallback by pinning the plan first, rather than asserting against a plan that had
  already excluded the failing provider.

---

## SMOKE VIDEO STATUS

**A real MP4 was produced through the new runtime, end to end.**

Verified properties of the output:

- Container/codec: `h264`, `1280x720`, `30fps`, audio `aac`
- Quality control: **10 checks passed**
- Fallbacks: **zero** — meaning the render used the real `sapi` TTS engine, the real
  `legacy_html` renderer driving Edge, and real FFmpeg. No mock was substituted.

A hand-written IR V2 document, `examples/minimal-ir-v2.json` (2 scenes), validates and
renders to a **10.92 s** MP4. This file exists specifically to prove the IR is
hand-authorable — that a human or an agent can write the project model directly without
going through the legacy format.

### Visual quality verification

Per-scene PSNR was measured across the rendered output after the zoompan fix:

| Scene | PSNR |
| --- | --- |
| 1 | 54.9 dB |
| 2 | 42.3 dB |
| 3 | 42.5 dB |
| 4 | 22.4 dB |

The first three are comfortably above the 35 dB stability threshold. Scene 4 is lower,
which is expected: it is not a static shot, so consecutive frames legitimately differ.
The point of the measurement was to catch a *still* shot being resampled into mush, and
that is no longer happening.

---

## KNOWN ISSUES

Stated plainly, without hedging.

1. **The only working TTS is `sapi`.** It is a Windows fallback with 2 system voices and
   limited prosody control. It is honest but it is not good. `moss` is declared but its
   binary is not installed. No neural TTS is wired.

2. **The only working renderer is `legacy_html`.** It renders the original ten templates
   through Edge. `advanced_html` — the renderer intended to consume IR V2's motion and
   layout semantics properly — is **not implemented**. The current path translates IR V2
   down to the legacy template format, which means the framework's richer motion
   vocabulary is not yet fully expressed on screen.

3. **`openai_compatible` has no credentials**, so all LLM work falls back to `mock_llm`.
   The project is fully functional without a model, but it will not write anything
   original until a key is supplied.

4. **A stale virtualenv remains at
   `C:\Users\Administrator\Documents\Codex\2026-09-14\sao-m\work\codex-projects\html-video-workflow\.venv`**
   (~3 400 files) and it is **broken** — it is missing `annotated_types`, so importing
   pydantic from it fails. The working environment is `D:\html-video-workflow\venv`.
   Deleting the C: copy requires explicit user approval under the safe-delete policy;
   it has not been removed. **This is a live footgun** — anyone who activates `.venv`
   out of habit will see confusing import errors.

5. **Screenshots were not sent to a model for aesthetic review.** Quality checks are
   programmatic (PSNR, dimensions, codec, duration, audio presence). No visual
   judgement beyond my own inspection was applied.

6. **No long-duration or multi-sequence project has been rendered.** The largest verified
   render is a short multi-scene piece. Scaling behaviour is untested.

---

## FILES CHANGED

### New — documentation

| File | Purpose |
| --- | --- |
| `FOUNDATION_REPORT.md` | This report |
| `ARCHITECTURE.md` | Layer map, boundaries, design rules |
| `CURRENT_STATUS.md` | Verified-working state, honestly labelled |
| `ROADMAP.md` | Phases 1–5 with an explicit out-of-scope list |
| `DECISIONS.md` | Decision records D-001 … D-007 |
| `DEVELOPMENT.md` | Setup, running, testing, conventions, adding a provider |
| `AGENT_HANDOFF.md` | Entry point for a successor agent |
| `docs/research/README.md` | Findings R-001 … R-008 and open questions |
| `references/visual-design-principles.md` | Motion semantics, duration-is-content, review checklist |
| `integrations/mcp/README.md` | MCP skeleton and planned tool surface |

### New — code and tooling

| File | Purpose |
| --- | --- |
| `scripts/dev.py` | Single launcher: `setup / doctor / test / serve / studio / render / clean` |
| `scripts/export_schema.py` | Schema generation, with `--check` mode for CI |
| `schemas/video_ir_v2.schema.json` | Generated from the Pydantic models |
| `examples/minimal-ir-v2.json` | Hand-written 2-scene IR V2 document |

### Modified — the original project

`README.md` was updated to describe the foundation layer and link the new documents. The
English and 简体中文 sections were both extended; the original workflow description, the
`SKILL.md` pointer, and the `references/project-schema.md` pointer are all preserved.

No other original file was rewritten. Specifically, `scripts/workflow.py`,
`scripts/sapi_tts.ps1`, and `agents/openai.yaml` are byte-for-byte untouched.

### Defects fixed during this phase

Seven real defects were found and fixed, each with the reasoning recorded:

| # | Defect | Root cause | Fix |
| --- | --- | --- | --- |
| 1 | Registry silently loaded only 1 of 9 providers | `except Exception` + `log.warning` swallowed a real import error | Record failures in `_LOAD_FAILURES`, log at error level, expose `load_failures()` |
| 2 | `ensure_loaded()` never re-ran after `clear()` | Guarded on `if not _REGISTRY`; provider modules are plain imports, so after a clear an empty registry never triggered the `@register` decorators again | Explicit `_LOADED` flag |
| 3 | Routing rejection reason did not name the blocker | Reason text was `No API key found (...)` | Prepend `missing credentials — ` so the cause is greppable |
| 4 | Job manifest disagreed with itself | `create_job()` left unsaved projects without an id; the plan did not carry the requested preset | Assign a real project id; propagate preset to the plan |
| 5 | Project id and job id diverged | `save_project()` did not stamp the generated id back onto the caller's object | Stamp the id back on both dict and model inputs |
| 6 | **Rendered stills washed out and blurry mid-shot** | `zoompan d=<frames>` with `-loop 1` made zoompan emit `<frames>` outputs per input frame while still re-evaluating `z`, so zoom raced past its 1.04 cap and resampled the still | `d=1` with explicit centred `x`/`y` — one output frame per input frame |
| 7 | `C:\d\html-video-workflow` created by accident | Git Bash's `/d/...` was passed straight to `Path()`, which treats a leading `/` as relative on Windows | `_normalize_env_home()` normalises Windows, POSIX and Git Bash spellings and rejects relative paths loudly |

Defect 6 was the significant one. It was diagnosed by isolating each filter
individually — the standalone HTML screenshot was crisp, `zoompan` alone was fine,
`fade` alone was fine, so the fault had to be in the composition — and then confirmed by
measuring the raw segment. Quantitatively: **PSNR(0.6 s, 3.6 s) = 10.1 dB when broken,
48.8 dB when fixed.** Output file size also dropped from 1.07 MB to 562 KB, because the
encoder was no longer fighting blurred input.

---

## NEXT

Ordered by value, not by effort.

### Immediate housekeeping

1. **Delete the stale C: `.venv`** (requires user approval). Until it is gone, it is a
   trap. The working environment is `D:\html-video-workflow\venv`.

### Phase 1 — real local TTS

2. Install and wire one genuine neural TTS engine so `sapi` stops being the ceiling.
   `fish_speech` and `cosyvoice` are already declared in the fallback chain and ranking
   table, so this is mostly a matter of implementing their probe and synthesis paths and
   letting routing pick them up.

### Phase 2 — `advanced_html` renderer

3. This is the highest-leverage remaining item. The IR V2 motion vocabulary
   (`reveal / count / trace / connect / split / depth / progression / focus / drift`) is
   currently flattened into legacy templates. Until `advanced_html` exists, the design
   work encoded in `references/visual-design-principles.md` is not actually reaching the
   screen.

### Later

4. An LLM key, so `openai_compatible` stops falling back to `mock_llm`.
5. A multi-sequence, longer-duration render, to test scaling behaviour.
6. Wire an actual MCP tool surface over the existing REST API — the skeleton and rules
   are already in `integrations/mcp/README.md`.

### What must not be done next

Do not start on avatar generation, cloud services, accounts, a marketplace, or a
timeline editor. Phases 1 and 2 above are prerequisites; building on top of a renderer
that cannot yet express the IR would bake the wrong abstractions in.

---

## VERIFICATION COMMANDS

To reproduce every claim in this report:

```bash
export HVW_HOME="D:/html-video-workflow"

# 75 tests, typecheck included
python scripts/dev.py test

# honest machine report
python scripts/dev.py doctor

# schema drift
python scripts/export_schema.py --check

# real end-to-end render from hand-written IR
python scripts/dev.py render examples/minimal-ir-v2.json
```

Expected: 75 passed; `doctor` showing `moss` as `--` and `openai_compatible` as `??`;
`OK schemas\video_ir_v2.schema.json matches the models`; and an `h264 / aac` MP4 at
`1280x720 / 30fps` with zero fallbacks.
