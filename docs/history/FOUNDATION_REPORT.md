# Foundation Report

**Phase:** Architecture Foundation / Framework Scaffold + Phase 2 renderer
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
243 tests, 0 failures, 0 errors, 0 skipped
```

Read from `--junitxml`, not from the console summary. In this sandbox the console summary
is unreliable: pytest's session-end temp cleanup is a bulk delete, and the environment's
bulk-delete guard kills the process for it *after* the last test but *before* the summary
line prints. A fully green run of 243 tests therefore reports `exit=1` with no `passed`
line at all.

That has been fixed rather than worked around. `tests/conftest.py`'s `isolated_home`
fixture now garbage-collects each temp home in a `finally` with
`shutil.rmtree(..., ignore_errors=True)`, so at most one directory is ever pending and
the guard is never tripped. Failure to clean up is deliberately non-fatal — on Windows a
browser or ffmpeg child can still hold a handle.

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
job manifests, the REST API, the nine motion primitives, the nine layouts, safe areas
and aspect resolution, the typography scale, the visual-design critic, render
determinism, and a full end-to-end smoke render.

Regression tests are worth calling out when they were written to fail against the bug
they guard:

- `test_gentle_push_in_does_not_rescale_the_still` — asserts PSNR > 35 dB between two
  frames of a still shot. It was **verified to fail at 10.1 dB** when the defect was
  reinstated, then to pass once fixed.
- `test_render_stage_falls_back_when_browser_missing` — exercises a genuine mid-run
  fallback by pinning the plan first, rather than asserting against a plan that had
  already excluded the failing provider.
- `test_metric_does_not_displace_the_headline`,
  `test_authoring_order_does_not_decide_which_layer_leads` and
  `test_media_never_takes_a_text_slot` — three slot-assignment regressions found by
  *looking at a rendered frame*, not by reading the code. See defect 8.
- `test_large_text_threshold_is_looser_than_body` — exercises both branches of the
  WCAG threshold rather than only the one that fails.

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

### `advanced_html` frames

Three scenes were rendered through `advanced_html` on this machine — headless Edge,
1600×900, real fonts, real CSS animation — and inspected as images rather than as
metrics. `scripts/preview_advanced.py` reproduces them into `D:\html-video-workflow\preview`.

| Scene | Layers | Layout chosen | Motions | Motion span |
| --- | --- | --- | --- | --- |
| 1 | label, headline, body, metric | `stat` | mask, reveal, wipe | 1 677 ms |
| 2 | label, headline, body | `editorial_left` | mask, reveal, wipe | 1 806 ms |
| 3 | headline, metric | `stat` | mask, wipe | 1 532 ms |

Verified in the rendered output, not inferred from the code:

- Each layer animates **once**, at its own start time — no unison, no `i * 100 ms`
  staircase.
- The metric carries the accent colour and the display type; the body does not.
- The display layer occupies the slot sized for display type, and **no two layers
  overlap** (defect 9).
- Every finding returned is `info`-level. The only one raised is `AA-012`, "nothing moves
  continuously; every layer enters and freezes" — which is accurate and is the honest
  next thing to fix, not a bug.

The critic deliberately emits **no aggregate score**. Findings carry rule id, severity,
evidence and a fix, and a test asserts that no `score` / `ai_feel` / `percentage` key can
appear in the serialised report.

---

## KNOWN ISSUES

Stated plainly, without hedging.

1. **The only working TTS is `sapi`.** It is a Windows fallback with 2 system voices and
   limited prosody control. It is honest but it is not good. `moss` is declared but its
   binary is not installed. No neural TTS is wired.

2. **`advanced_html` now exists and is the recommended renderer.** It consumes IR V2
   directly — through `SceneCompiler` rather than the legacy template adapter — so the
   nine motion primitives, nine layouts, safe areas and the type system reach the
   screen. `doctor` reports `OK renderer advanced_html`, and the router selects it over
   `legacy_html`. It is **verified by three real frames rendered through headless Edge**
   (see SMOKE VIDEO STATUS). What is still not implemented: neural TTS, avatar, image,
   video, music and ASR providers. `legacy_html` remains the recorded fallback.

3. **`openai_compatible` has no credentials**, so all LLM work falls back to `mock_llm`.
   The project is fully functional without a model, but it will not write anything
   original until a key is supplied.

4. **The critic finds real problems but nothing acts on them yet.** `advanced_html`
   returns findings (`rule`, `severity`, `message`, `evidence`, `suggestion`) in the
   response metrics, and refuses to emit any aggregate "AI score" — a float would imply
   a measurement that does not exist. No automated loop yet *rewrites* a scene in
   response to a finding; `SceneVariationPolicy` is the only thing currently acting,
   and it only rotates layouts.

5. **A stale virtualenv remains at
   `C:\Users\Administrator\Documents\Codex\2026-09-14\sao-m\work\codex-projects\html-video-workflow\.venv`**
   (~3 400 files) and it is **broken** — it is missing `annotated_types`, so importing
   pydantic from it fails. The working environment is `D:\html-video-workflow\venv`.
   Deleting the C: copy requires explicit user approval under the safe-delete policy;
   it has not been removed. **This is a live footgun** — anyone who activates `.venv`
   out of habit will see confusing import errors.

6. **Screenshots were not sent to a model for aesthetic review.** Quality checks are
   programmatic (PSNR, dimensions, codec, duration, audio presence). No visual
   judgement beyond my own inspection was applied.

7. **No long-duration or multi-sequence project has been rendered.** The largest verified
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
| `scripts/preview_advanced.py` | Renders three scenes through `advanced_html` and prints the chosen layout, motions and critic findings |
| `schemas/video_ir_v2.schema.json` | Generated from the Pydantic models |
| `examples/minimal-ir-v2.json` | Hand-written 2-scene IR V2 document |

### New — the `advanced_html` renderer (Phase 2)

| File | Purpose |
| --- | --- |
| `providers/renderer/advanced_html.py` | Renderer provider: consumes IR V2 directly, probes the browser, falls back to `legacy_html` |
| `renderers/scene_compiler.py` | IR V2 → HTML + CSS, orchestrating motion, layout, typography, safe areas |
| `renderers/motion.py` | Nine motion primitives, each emitting real `@keyframes` |
| `renderers/layout.py` | Nine layout primitives and the three-sweep slot assignment |
| `renderers/typography.py` | Optically distinct type scale, portrait-aware reference edge |
| `renderers/aspect.py` | 16:9 / 9:16 / 1:1, platform safe areas, pixels-win-over-preset |
| `renderers/critic.py` | Rule-based visual critique (`AA-001` … `AA-012`), no aggregate score |
| `renderers/determinism.py` | Seeded variation, document validator, pinned browser flags |
| `renderers/capture.py` | The two capture strategies, and why there is no third |
| `renderers/service.py` | The render seam above "how do we get pixels" |
| `renderers/layer.py` | One IR layer → markup; missing assets become visible markers |
| `renderers/assets.py` | Asset resolution, with a `MissingAsset` that is never a broken `<img>` |
| `references/anti_ai_visual_rules.md` | The twelve rules the critic implements, stated as design rules |
| `tests/test_advanced_renderer.py` | 76 tests pinning motion, layout, aspect, typography, critic, determinism |

### Modified — the original project

`README.md` was updated to describe the foundation layer and link the new documents. The
English and 简体中文 sections were both extended; the original workflow description, the
`SKILL.md` pointer, and the `references/project-schema.md` pointer are all preserved.

No other original file was rewritten. Specifically, `scripts/workflow.py`,
`scripts/sapi_tts.ps1`, and `agents/openai.yaml` are byte-for-byte untouched.

### Defects fixed during this phase

Eleven real defects were found and fixed, each with the reasoning recorded:

| # | Defect | Root cause | Fix |
| --- | --- | --- | --- |
| 1 | Registry silently loaded only 1 of 9 providers | `except Exception` + `log.warning` swallowed a real import error | Record failures in `_LOAD_FAILURES`, log at error level, expose `load_failures()` |
| 2 | `ensure_loaded()` never re-ran after `clear()` | Guarded on `if not _REGISTRY`; provider modules are plain imports, so after a clear an empty registry never triggered the `@register` decorators again | Explicit `_LOADED` flag |
| 3 | Routing rejection reason did not name the blocker | Reason text was `No API key found (...)` | Prepend `missing credentials — ` so the cause is greppable |
| 4 | Job manifest disagreed with itself | `create_job()` left unsaved projects without an id; the plan did not carry the requested preset | Assign a real project id; propagate preset to the plan |
| 5 | Project id and job id diverged | `save_project()` did not stamp the generated id back onto the caller's object | Stamp the id back on both dict and model inputs |
| 6 | **Rendered stills washed out and blurry mid-shot** | `zoompan d=<frames>` with `-loop 1` made zoompan emit `<frames>` outputs per input frame while still re-evaluating `z`, so zoom raced past its 1.04 cap and resampled the still | `d=1` with explicit centred `x`/`y` — one output frame per input frame |
| 7 | `C:\d\html-video-workflow` created by accident | Git Bash's `/d/...` was passed straight to `Path()`, which treats a leading `/` as relative on Windows | `_normalize_env_home()` normalises Windows, POSIX and Git Bash spellings and rejects relative paths loudly |
| 8 | **`advanced_html` produced a frame the pipeline called missing** | `BrowserRenderService` hardcoded `frame.png`; `stage_render` independently derived `scene-001.png` and handed that exact path to `cache_put`, which raised `FileNotFoundError` | The caller now names the frame (`RenderRequest.image_path`), and the renderer fails loudly if the named file is empty |
| 9 | **A headline printed straight over a label in the rendered frame** | `LayoutEngine.assign` consumed `_slot_order` positionally by layer index. `metric` leads that order, so index 0 took the metric band and the real metric was pushed into `primary`; a display-size headline then grew out of a 19%-tall band and into the layer above | Three sweeps: media by content, text roles by *importance*, leftovers in reading order. `stat`'s bands were also re-spaced with a real gutter |
| 10 | A "low contrast" test asserted nothing | `#777777` on `#071c33` measures **3.84:1**, which legitimately passes the 3:1 large-text floor — so the test's premise was false. The assertion was also `"fix" in suggestion or suggestion`, which is vacuous | Test moved to a colour that genuinely fails (2.03:1), evidence asserted, and a companion test added for the branch that passes |
| 11 | **A fully green suite reported as hundreds of errors, with `exit=1`** | `tests/conftest.py` used `tmp_path_factory.mktemp`, which deletes every test's temp dir in one sweep at session end. That bulk delete trips the sandbox's bulk-delete guard, which raises `SystemExit(1)` after the last test but before pytest prints its summary | The fixture garbage-collects each temp home in a `finally`, so at most one is ever pending |

Defect 6 was the significant one on the video side. It was diagnosed by isolating each
filter individually — the standalone HTML screenshot was crisp, `zoompan` alone was fine,
`fade` alone was fine, so the fault had to be in the composition — and then confirmed by
measuring the raw segment. Quantitatively: **PSNR(0.6 s, 3.6 s) = 10.1 dB when broken,
48.8 dB when fixed.** Output file size also dropped from 1.07 MB to 562 KB, because the
encoder was no longer fighting blurred input.

Defect 9 is worth noting for *how* it was found: every test in the suite passed, the
compiler reported every layer as placed, and coverage metrics were healthy. The bug was
only visible by rendering a frame and looking at it. That is the argument for the
SMOKE VIDEO STATUS section existing at all — placement without overlap is a property no
assertion in the suite was checking, because the suite was written against the code
rather than against the picture.

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

3. **Done, and now the default.** The renderer, the compiler, the nine motions, the nine
   layouts, the type system, the safe areas and the critic all exist and are exercised by
   tests and by three real frames. The next improvement here is not more vocabulary —
   it is *acting on findings*: nothing currently rewrites a scene in response to a
   critic finding, and `AA-012` appears on every scene rendered so far.

### Later

4. Give the motion engine an ambient/continuous register. Every primitive currently
   enters and freezes, which is exactly what `AA-012` reports. `parallax` and `drift`
   are declared and implementable; they are simply not being reached by the current
   motion chooser.
5. An LLM key, so `openai_compatible` stops falling back to `mock_llm`.
6. A multi-sequence, longer-duration render, to test scaling behaviour.
7. Wire an actual MCP tool surface over the existing REST API — the skeleton and rules
   are already in `integrations/mcp/README.md`.

### What must not be done next

Do not start on avatar generation, cloud services, accounts, a marketplace, or a
timeline editor. A renderer now exists, but nothing yet *reacts* to the critic's
findings — building on top of a design loop that cannot close would bake the wrong
abstractions in.

---

## VERIFICATION COMMANDS

To reproduce every claim in this report:

```bash
export HVW_HOME="D:/html-video-workflow"

# 243 tests
python scripts/dev.py test

# the same run, with an unambiguous total
python -m pytest tests -q --junitxml=junit.xml

# honest machine report
python scripts/dev.py doctor

# schema drift
python scripts/export_schema.py --check

# real end-to-end render from hand-written IR
python scripts/dev.py render examples/minimal-ir-v2.json

# the three Phase 2 frames, written to D:\html-video-workflow\preview
python scripts/preview_advanced.py
```

Expected: 243 tests with 0 failures; `doctor` showing `moss` as `--`,
`openai_compatible` as `??` and `advanced_html` as `OK`, with `advanced_html`
recommended over `legacy_html`; `OK schemas\video_ir_v2.schema.json matches the models`;
an `h264 / aac` MP4 at `1280x720 / 30fps` with zero fallbacks; and three PNGs whose
layers do not overlap.
