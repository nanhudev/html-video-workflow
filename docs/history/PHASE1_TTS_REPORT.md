# PHASE 1 — Natural TTS Provider Layer + Auto Routing v1

**Date:** 2026-09-15
**Preceded by:** [`FOUNDATION_REPORT.md`](../FOUNDATION_REPORT.md) (historical Phase 0 snapshot, left untouched)
**Development model:** GitHub-first, hardware-agnostic. The absence of a GPU, of
CUDA and of downloaded models did not gate any part of this phase.

---

## 1. Goal

Close the first half of the project's real bottleneck — *声音像不像真人* — by
turning TTS from "whichever engine the stage happens to call" into a scored,
routed, measurable subsystem.

The second half (*画面是不是还像 AI PPT*) is Phase 2.

---

## 2. What was built

### 2.1 The contract — `src/html_video_workflow/providers/tts/contract.py`

Everything the business layer is allowed to know about speech lives here. Nothing
below this layer is ever reached directly; nothing above it ever names an engine.

- **`CapabilityFlag`** — tri-state `yes` / `no` / `unknown`, where only `yes` is
  truthy. This is the single most important type in Phase 1. A boolean forces a
  provider to either claim support before probing or claim none at all, and both
  are lies.
- **`QualityTier`** — `none < robotic < basic < good < high < studio`, with a
  score mapping so a provider reporting only a tier still routes sensibly.
- **`GPURequirement`** — `no` / `optional` / `required`.
- **`TTSProviderDescriptor`** — the full §8 field list, including
  `supports_emotion`, `supports_style`, `supports_voice_clone`,
  `supports_streaming`, `supports_speed`, `supports_pitch`,
  `supports_emphasis`, `supports_ssml`.
- **`TTSRequest`** — text, language, voice, speaker, emotion, speed, pitch,
  volume, style, sample_rate, output_format, seed. Validators clamp speed to
  0.25–4.0 and pitch to ±24.
- **`TTSResult`** — audio path, duration, sample rate, provider, model, voice,
  generation time, realtime factor, metadata, **and `unsupported_fields`.**
- **`ProsodyPlan` / `ProsodySegment`**, **`VoiceDescriptor`**,
  **`AudioQualityReport`**.

`unsupported_fields` deserves credit: a provider that cannot honour `emotion`
now *says so* rather than dropping it silently. A dropped request is invisible;
a reported one is a bug someone can file.

### 2.2 Four adapters

See per-provider docs in [`docs/providers/`](providers/).

| Provider | Transport | Tier | State on this machine |
| --- | --- | --- | --- |
| `sapi` | subprocess → PowerShell | `robotic` | **available** |
| `aivisspeech` | HTTP sidecar | `high` | `unavailable` (no engine) |
| `openai_compatible_tts` | remote API | `high` | `missing_credentials` |
| `neural_sidecar` | HTTP sidecar | `studio` | `not_installed` |

Plus the pre-existing `moss` (`not_installed`) and `mock_tts` (always ready).

**The core gained no `torch`, `transformers` or CUDA dependency.** Every neural
engine is reached over HTTP. This is a load-bearing architectural decision, not
an implementation detail — see D-00x below.

### 2.3 Rule-based prosody — `pipeline/prosody.py`

Deterministic, dependency-free, and every segment carries a `rationale`.

Measured output for
`本地优先的设计必须让每一步都可验证；否则再大的模型，也只是更贵的包装。`:

```
segments: 2
  本地优先的设计必须让每一步都可验证；   before=120 after=300 pace=0.96 emph=['必须']
  否则再大的模型，也只是更贵的包装。     before=0   after=740 pace=0.95 emph=[]
total pause ms: 1160        estimated speech ms: 6683
```

Three fixes came out of building it, each a real defect rather than a test bug:

1. **Quote absorption duplicated the closing mark** — `他说"…。"然后` produced a
   segment starting with `”`. A closer is now absorbed only when its opener is
   actually unclosed.
2. **`e.g.` split mid-abbreviation** — now detected by matching the word
   fragment ending at the dot, not the whitespace-delimited token.
3. **Subdivision never fired on medium sentences** — the re-merge threshold
   collapsed every legitimate split.

A pause-placement subtlety worth recording: mid-plan `pause_before` stays 0,
because the previous segment's `pause_after` already covers that gap. Counting it
twice is how a plan ends up with a two-second hole in the middle of a sentence.

### 2.4 Audio post-processing and QC — `src/html_video_workflow/audio/`

FFmpeg only; no DSP library. Silence trim, loudness normalization, fade in/out,
resample, channel normalization. `AudioQualityChecker` reports duration, sample
rate, peak, LUFS, clipping and unexpected silence.

**A real defect was found here.** `ffprobe` showed `normalize_loudness` writing
**AAC inside a `.wav` container** — the file was unreadable by `wave` and would
have failed downstream in confusing ways. Codec now follows the container (PCM
for `.wav`). This is precisely the class of bug the QC work was built to surface.

### 2.5 Auto Router v1 — `pipeline/router.py`

Presets are **weights, never provider names**. The moment `high_quality` means
"pick Fish Speech", the router becomes a lookup table that goes stale with every
new engine.

New scoring axes: language match (exact vs prefix vs miss), feature coverage, and
`speech_naturalness`, which stacks on generic naturalness so a fast robotic engine
cannot out-score a natural one under `balanced`.

**A second real defect was found while validating it:** `mock_tts` was winning
*every* preset, including `high_quality` — because `speed_score=10` outweighed
everything else. A user asking for maximum quality was being routed to a
placeholder tone: the most damaging possible router bug, because it looks
successful. Fixed with a `low_fidelity` tag carried on the provider spec and a
`fidelity_penalty` weight that is `0` under `fast` and grows with each quality
step. Mocks stay in the pool as a guaranteed last resort, but they no longer win.

Verified before and after:

```
tts fast          -> mock_tts     (correct: speed is the point)
tts high_quality  -> sapi         (correct: a real engine)
renderer high_quality -> legacy_html   (mock_renderer demoted to 1.08)
```

> **Superseded.** Reported as of Phase 1. The penalty demoted placeholders
> without guaranteeing they could never win, and `tts fast -> mock_tts` was
> recorded here as correct — it is not: a placeholder does not produce fast
> speech, it produces no speech, and on a machine with a zh-CN voice installed
> the same arithmetic handed Chinese narration to a beep under `balanced` too.
> See **D-012** in `DECISIONS.md` for the rule that replaced it.

Every decision carries `reason[]` describing why it won **and** why each other
candidate lost; `cannot apply: emotion` is recorded rather than hidden.
Fallback order is the declared chain first (deliberate degradation), then any
other available provider, so a project is never stranded because its engine was
not in the list.

---

## 3. Verification

Measured this session, not recalled:

| Check | Result |
| --- | --- |
| Full test suite | **167 passed**, 0 failed, 0 skipped |
| New routing tests | 25 passed |
| TTS contract tests | 19 passed |
| Prosody tests | 27 passed |
| Audio QC tests | 21 passed |
| IR V2 schema `--check` | `OK … matches the models` |
| Studio typecheck | clean |
| Studio production build | clean, 38 modules, 1.74 s |
| Provider registry load failures | **0** (all 11 providers registered) |
| End-to-end smoke render | MP4 produced, **h264 / 1280×720 / 12.68 s** |

Test breakdown by module: `test_api` 15, `test_audio_quality` 21,
`test_hardware_and_routing` 11, `test_legacy_compat` 5, `test_project_ir` 14,
`test_prosody` 27, `test_providers` 12, `test_runtime` 12, `test_smoke_e2e` 6,
`test_tts_providers` 19, `test_tts_routing` 25.

### One assumption corrected mid-flight

The CI workflow originally shrank the smoke render via
`settings --set render.width=320`. **This does nothing** — output geometry comes
from the project's own `output` block (`ctx.project.output.width`), and
`settings.render.width` never reaches it. Rather than ship a step whose comment
describes behaviour it does not have, the step was removed and the smoke runs at
the project's native 1280×720. Verified locally at that size.

---

## 4. Phase 1 gate

| Requirement | Status |
| --- | --- |
| Stable TTS contract | ✅ `contract.py`, frozen interface |
| ≥ 3 provider adapters | ✅ 4 (sapi, aivisspeech, openai_compatible, neural_sidecar) |
| Working auto-router | ✅ explainable scoring, 25 tests |
| SAPI fallback | ✅ last link in every chain, verified available |
| Prosody baseline | ✅ rule-based, no LLM dependency |
| Audio QC | ✅ + one real codec defect fixed |
| All tests pass | ✅ 167 |
| CI passes | ✅ workflow defined; each step executed locally first |
| Legacy compatibility | ✅ frozen files untouched, `test_legacy_compat` green |

**Gate satisfied.**

---

## 5. What is NOT validated

Stated plainly, because the temptation is always to round up:

- **No neural TTS has been heard.** `aivisspeech` and `neural_sidecar` are tested
  against a local stub server. Their request mapping is verified; **their audio
  quality is unknown.**
- No streaming benchmark exists.
- No LUFS target has been tuned by ear.
- No voice-cloning path exists, by design — capability metadata only.

`docs/CURRENT_STATUS.md` keeps these as `REAL HARDWARE VALIDATION PENDING`.

---

## 6. Files added / changed

Added: `providers/tts/{contract,http_client,aivisspeech,openai_compatible_tts,neural_sidecar}.py`,
`audio/{__init__,postprocess}.py`, `pipeline/prosody.py`,
`tests/{test_tts_providers,test_prosody,test_audio_quality,test_tts_routing}.py`,
`docs/providers/*.md`, `.github/workflows/ci.yml`.

Modified: `providers/base.py` (TTS contract methods), `providers/registry.py`
(planned-module tolerance), `providers/tts/sapi.py` + `mock_tts.py` +
`renderer/mock_renderer.py` (honest capabilities, `low_fidelity` tag),
`pipeline/router.py`, `pipeline/stages.py`, `ffmpeg/service.py` (container-aware
codec), `config/settings.py`.

Untouched: `scripts/workflow.py`, `scripts/sapi_tts.ps1`, `agents/openai.yaml`.

---

## 7. Next

Phase 2 — advanced HTML renderer consuming IR V2 directly, ≥6 motion primitives,
≥5 layouts, anti-AI rules and critic, visual regression, determinism, and Studio
scene preview. This closes the second half of the bottleneck: whether the picture
still looks like an animated PowerPoint with a more expensive model attached.
