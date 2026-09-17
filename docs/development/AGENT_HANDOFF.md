# Agent Handoff

You are picking up `html-video-workflow` from another agent. Read this first; it
saves you from rediscovering things the hard way.

Repo: `https://github.com/nanhudev/html-video-workflow`
Local: `C:\Users\Administrator\Documents\Codex\2026-09-14\sao-m\work\codex-projects\html-video-workflow`

---

## 1. What this project is

A **Local-first Agentic Video Studio**. It turns a project IR into a rendered
video using providers that run on the user's machine whenever possible.

```
Agent decides · IR describes · Provider executes · Runtime schedules
Studio visualizes · Quality System verifies
```

It began as a small Codex Skill package (one 300-line script + HTML templates).
The Foundation phase added an architecture around it **without breaking it**.

## 2. Read these in order

| File | Why |
|---|---|
| `CURRENT_STATUS.md` | what works right now, verified |
| `DECISIONS.md` | why the architecture is shaped this way |
| `ROADMAP.md` | what is next, and what is deliberately not |
| `ARCHITECTURE.md` | layer responsibilities, IR, routing |
| `DEVELOPMENT.md` | setup, conventions, troubleshooting |
| `VIDEO_IR_V2.md`, `PROVIDER_SPEC.md`, `HARDWARE_ROUTING.md` | layer specs |
| `references/visual-design-principles.md` | the anti-AI-feel rules |

## 3. Environment (this machine)

```bash
# Interpreter — use the D: venv, NOT the stale C: one
D:/html-video-workflow/venv/Scripts/python.exe

# Data home (heavy state lives here, never in the repo)
HVW_HOME='D:\html-video-workflow'

# Run things
D:/html-video-workflow/venv/Scripts/html-video.exe doctor
D:/html-video-workflow/venv/Scripts/python.exe -m pytest tests -q
```

**Pitfall:** `D:/html-video-workflow/venv/Scripts/pip.exe` points at a stale
`C:\...\.venv`. Always use `python.exe -m pip` instead of `pip.exe`.

**Pitfall:** in Git Bash, `HVW_HOME=/d/html-video-workflow` works (it is
normalised), but any *relative* value now raises on purpose — it used to silently
create a `\d\html-video-workflow` directory inside the repo.

**Pitfall:** this shell needs `export PATH="/usr/bin:/bin:$PATH"` prefixed, or
`ls`/`dirname` are "not found". Also: never call `powershell.exe` directly from
Bash (`Command blocked for security`); call it via Python `subprocess` — that is
what `hardware/profile.py` and `providers/tts/sapi.py` do.

## 4. Task management

**Work autonomously.** Do not stop to ask unless an operation is irreversible,
paid, requires auth, deletes user data, or needs a secret. The user has stated
they will not cancel and expect continuous progress.

## 5. Hard constraints

These are not stylistic preferences; breaking them is a regression.

1. **`scripts/workflow.py`, `scripts/sapi_tts.ps1`, `agents/openai.yaml` stay
   byte-identical.** They are the compatibility surface. Reach the legacy code
   only through `legacy/adapter.py`. `tests/test_legacy_compat.py` guards this.
2. **Never report success without a probe.** No `Ready` / `Available` /
   `passed` from a static value. `ProviderSpec` is a claim; `ProbeResult` is
   truth; `Capability` may only confirm or downgrade.
3. **No silent degradation.** Every provider substitution appends to
   `job.fallbacks` as `{stage, from, to, reason}`.
4. **The IR stays renderer-neutral.** No `remotionComponent`, `cssClass`, or
   template ids in the data. Guarded by `test_document_is_renderer_neutral`.
5. **Heavy artifacts stay outside the repo**, on the data drive when present.
6. **Tests never download models or call a paid API.**

## 6. Bugs already found and fixed

Do not reintroduce these. Each has a regression test.

### `save_project()` did not stamp the id onto the caller's object
A CLI that saved an id-less project and then handed the same object to the runtime
produced **two ids**: the manifest landed in one project directory and the run's
frames/audio/segments in another, orphaning every artifact. Fixed by writing the
generated id back onto the passed object. Test:
`test_saved_project_and_job_agree_on_id`.

### `discover_builtins()` swallowed import failures
A single failing module import silently removed a whole provider domain, which
surfaced as 21 test failures with no error message. Failures now go to
`registry.load_failures()` and are logged at error level. Discovery is guarded by
an explicit `_LOADED` flag because the provider modules are plain `import`s —
after `clear()`, an `if not _REGISTRY` check would never re-run the `@register`
decorators and the registry would stay empty forever.

### `zoompan` rescaled the still instead of nudging it
`zoompan` was given `d=<segment frames>`. Because the image input is looped and
`-t` already bounds the segment, zoompan emitted `<frames>` outputs per input
frame while re-evaluating `z` every time, so the zoom raced past its 1.04 cap and
aggressively resampled the still. On screen: washed-out, blurry text for most of
a shot. Fixed with `d=1` plus explicit centred `x`/`y`. Measured as PSNR between
two mid-scene frames: **10.1 dB broken → ~49 dB fixed**; the test asserts > 35 dB,
and it was verified to fail when the bug is reinstated.

### `HVW_HOME` accepted relative paths
See the pitfall above. Fixed by normalising `/d/x` → `D:\x` and raising on
relative values.

### Probe endpoint was POST-only
The Studio issues a plain GET. Now exposed on both methods.

### `HardwareProfile.to_dict()` dropped derived values
`asdict()` skips `@property`, so `vram_total_mb` was missing from the API and a
consumer reading it got `undefined`. Now added explicitly.

## 7. Where to look when something breaks

| Symptom | Look at |
|---|---|
| A provider is missing | `registry.load_failures()` |
| A render silently degraded | `job.json` → `fallbacks[]` |
| Studio shows nothing | is `html-video serve` running on 8787? |
| Routing picked something odd | `/routing?preset=...` → `reasons[stage].candidates[].reason` |
| Output looks washed out | `ffmpeg/service.py` filter chain, check the zoom/PTS maths |

## 8. Suggested next steps

In priority order. See `ROADMAP.md` for the full reasoning.

1. **Wire a real local TTS provider.** `sapi` is the only working engine and
   `moss` reports absent. Keep `sapi` as the always-works fallback.
2. **`advanced_html` renderer.** `legacy_html` is a single-layer approximation
   of the semantics the IR already declares.
3. **`html-video models pull`.** Explicit, resumable, checksummed. Never
   auto-download during a render.
4. **Resolve the stale `C:\.venv`** (~3 400 files). Needs user approval; bulk
   delete is gated by the safety policy.
5. **`FOUNDATION_REPORT.md`** if the originating task still requires it.

## 9. Verification before you hand off

```bash
D:/html-video-workflow/venv/Scripts/python.exe -m pytest tests -q        # 75 passed
cd apps/studio && npm run typecheck && npm run build                      # clean
D:/html-video-workflow/venv/Scripts/python.exe scripts/export_schema.py --check   # OK
HVW_HOME='D:\html-video-workflow' D:/html-video-workflow/venv/Scripts/html-video.exe \
  create "smoke" --preset fast --render
```

Then confirm the MP4 with `ffprobe` (`h264` + `aac`) and check
`job.json` has empty `fallbacks` and `errors`. A green test suite that renders
nothing is not a pass.
