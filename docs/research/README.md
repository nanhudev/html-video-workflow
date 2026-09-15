# Research Notes

Findings that informed the architecture. Each entry records what was actually
verified, not what was assumed — and, where relevant, the measurement was taken on
the development machine (Windows 10, Ryzen 5 3600, RTX 2070 8 GB, 16 GB RAM).

---

## R-001 — The original repository was a Skill package, not an application

**Question.** What exactly are we extending?

**Finding.** `scripts/workflow.py` is a single ~300-line script driven by a JSON
file. It has no `requirements.txt`, no `tests/`, no package directory, and no
`__init__.py`. Rendering is: read JSON → pick one of ten hardcoded HTML templates
→ screenshot each scene with headless Edge → synthesise narration with SAPI via a
PowerShell helper → concat with ffmpeg.

**Consequences.** There was no seam to hook a runner into, and no test harness to
extend. That is why the Foundation phase builds a parallel package and reaches the
old code through a subprocess adapter rather than refactoring in place.

Full detail: `docs/architecture/legacy-audit.md`.

---

## R-002 — Headless Chromium screenshot timing

**Question.** How long must we wait before a headless screenshot is complete?

**Finding.** `--virtual-time-budget` makes the browser advance its own clock
rather than waiting in real time, which is both faster and deterministic. Testing
at 2500 ms and 6000 ms against the same document produced **byte-identical PNGs**
(113 729 bytes), confirming that the render settles well inside 2500 ms.

**Consequence.** Screenshots use `--virtual-time-budget=2500`. Raising it only
costs time.

**Caveat learned the hard way.** Because the budget is virtual, CSS animations
have *finished* by screenshot time. A dim or washed-out element in a rendered
still is therefore almost never an animation-timing problem — look at the
composition filters instead. This is exactly how the `zoompan` bug (see
`AGENT_HANDOFF.md`) was eventually isolated.

---

## R-003 — ffmpeg `zoompan` semantics on a looped still

**Question.** What is the correct `zoompan` configuration for a gentle push-in on
a single image?

**Finding.** With `-loop 1` the input is an endless frame stream and `-t` already
bounds the output, so `zoompan` must emit **one output frame per input frame**
(`d=1`). Setting `d=<frames>` makes zoompan hold each input frame and emit
`<frames>` outputs while still re-evaluating `z`, so the zoom races past its cap
and aggressively resamples the still.

Measured with PSNR between two mid-scene frames of a high-frequency test card:

| Configuration | PSNR(0.6s, 3.6s) |
|---|---|
| `d=<frames>` (wrong) | **10.1 dB** |
| `d=1` (correct) | **48.8 dB** |

Also note `x`/`y` must be set explicitly, or zoompan anchors the zoom at the
top-left corner instead of the centre.

**Consequence.** `FFmpegService.image_with_audio` uses `d=1` with centred `x`/`y`,
and `test_gentle_push_in_does_not_rescale_the_still` asserts >35 dB. This was
verified to fail when the bug is reinstated.

---

## R-004 — Probing GPU information on Windows without `wmic`

**Question.** How do we enumerate GPUs on a machine where `wmic.exe` is blocked
by security policy?

**Finding.** Three sources, in preference order:

1. `nvidia-smi --query-gpu=name,memory.total,driver_version` — the only source
   that reports **accurate VRAM**, and it names the discrete card precisely.
2. PowerShell CIM `Win32_VideoController` — broad coverage, but reports
   `AdapterRAM` as a signed 32-bit value, so cards ≥ 4 GB come back wrong or
   negative. Treat its VRAM as unknown rather than trusting it.
3. `lspci` (Linux) / `system_profiler` (macOS).

**Consequence.** `nvidia-smi` is tried first and its VRAM is authoritative. The
CIM fallback supplies names only. This is why the development machine reports an
RTX 2070 at 8192 MB while also listing two virtual display adapters with unknown
VRAM — the virtual adapters are not filtered, because the same filter would hide a
genuine secondary GPU.

---

## R-005 — RAM and CPU model without external tools

**Question.** How do we read total RAM and the marketing CPU name portably?

**Finding.** `wmic` is unavailable and `psutil` would be a hard dependency for two
values. Instead:

- RAM via `ctypes` → `GlobalMemoryStatusEx` (Windows), `/proc/meminfo` (Linux),
  `sysctl` (macOS).
- CPU marketing name via `winreg` → `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0\ProcessorNameString`.
  This is the string a human recognises ("AMD Ryzen 5 3600 6-Core Processor"),
  unlike `platform.processor()`.
- Physical vs logical cores from `os.cpu_count()` plus platform-specific queries.

**Consequence.** The hardware profiler has no third-party dependency and still
reports real values.

---

## R-006 — Why content-addressed caching keys on provider id + config hash

**Question.** What belongs in a cache key for a render?

**Finding.** Keying on input content alone is wrong in two directions: switching
themes or providers would serve a stale image, and re-running after a config change
would reuse output produced by the old config. Keying only on the request payload
is also insufficient because two providers can accept the same request and produce
very different results.

**Consequence.** `cache_key()` hashes *content + provider id + relevant config*.
The index lives at `<home>/cache/index.json` and entries whose file has vanished
are evicted on read, so a manually cleared cache directory cannot yield dangling
hits.

---

## R-007 — Narration-length estimation for CJK

**Question.** How do we size a scene before synthesis completes?

**Finding.** A naive `len(text) / chars_per_second` is badly wrong for Chinese,
which packs far more information per character than English. CJK code points must
be counted separately from Latin words, and punctuation carries pause weight.

**Consequence.** `utils/audio.estimate_speech_seconds()` is CJK-aware. It is used
only as a planning estimate — once real audio exists, `wav_duration()` is
authoritative.

---

## R-008 — Loudness normalisation is best-effort, never fatal

**Question.** Should two-pass EBU R128 normalisation be able to fail a render?

**Finding.** It is a re-encode of an already-complete video. A failure there costs
a quality improvement, not the user's work.

**Consequence.** `stage_compose` catches normalisation errors, records a note on
the step, and falls back to the un-normalised file. The job still completes and the
quality report still runs.

---

## Open questions

Not yet resolved; do not build on assumptions here.

- **Real acceleration headroom.** The RTX 2070 has 8 GB. Which local TTS and
  avatar models actually fit alongside a browser render, without a mid-run OOM?
  Needs measurement, not estimation.
- **Deterministic stills across machines.** Font availability changes layout. Font
  subsetting is the likely answer but is unproven here.
- **Benchmark warm-up.** First-run numbers include model load and disk cache
  effects. How many warm-up iterations before a benchmark is comparable?
- **CJK line breaking.** The caption track uses narration text verbatim; whether
  the renderer breaks lines at linguistically correct points is unverified.
