# Decision Records

Short, dated, and honest about trade-offs. Add an entry before making a choice
that would be expensive to reverse.

Format: **Context → Decision → Consequences → Alternatives rejected.**

---

## D-001 — Keep the legacy script frozen and wrap it

**Date:** 2026-09-14 · **Status:** accepted

**Context.** The repository began as a Codex Skill package: one 300-line
`scripts/workflow.py`, a PowerShell SAPI helper, and a set of HTML templates.
Users depend on `python scripts/workflow.py --project ... --out ...` working
exactly as documented.

**Decision.** Do not modify `scripts/workflow.py`, `scripts/sapi_tts.ps1` or
`agents/openai.yaml`. Build the new system beside them and reach the old code
through `html_video_workflow/legacy/adapter.py`, which loads it by path.

**Consequences.** Two code paths exist for a while, and the legacy one cannot
benefit from new features. In exchange, no existing user's command breaks, and
the legacy module doubles as a behavioural reference when the new renderer
disagrees with it. `tests/test_legacy_compat.py` asserts the frozen files still
contain their key definitions.

**Alternatives rejected.** Rewriting the script in place (breaks users, loses the
reference implementation); deleting it (destroys the only known-good baseline).

---

## D-002 — IR V2 is renderer-neutral, and V1 migrates losslessly

**Date:** 2026-09-14 · **Status:** accepted

**Context.** V1 scenes were a flat `{eyebrow, title, body, tags, metric}`. That
is really a single template's data model, and it cannot express motion, layout,
multiple layers, or a second renderer.

**Decision.** Introduce `Project ▸ Sequence ▸ Scene ▸ Shot ▸ Layer` where layers
are `{type, role, content, layout, motion}`. The IR may not contain
`remotionComponent`, `cssClass` or any renderer token. Migrate V1 by translating
each legacy field into a layer, and **keep the legacy fields on the model** so a
round-trip does not lose anything.

**Consequences.** The renderer has to interpret roles and semantics rather than
read a template id — more work now, but a second renderer becomes possible.
Migration is idempotent, and `detect_version()` treats a bare `scenes` list as V1.

**Alternatives rejected.** A `template` field in the IR (couples data to one
renderer); dropping V1 fields after migration (breaks round-tripping and any
existing tooling).

---

## D-003 — Providers declare a spec, but state comes from a probe

**Date:** 2026-09-14 · **Status:** accepted

**Context.** A provider knows what it *could* do, but not whether it *can* right
now — the browser may be uninstalled, the API key absent, the binary off PATH.

**Decision.** Split the two. `ProviderSpec` is a static, authored claim used for
ranking. `ProbeResult` is the result of an actual check. `Capability` is derived
from a probe and may only *confirm or downgrade* the spec. `Provider.capabilities()`
never returns `available=True` from the spec alone.

**Consequences.** Every listing costs a probe, so probes are cached and must stay
cheap. In exchange, a provider can never appear ready because someone typed
`available: true` into a dataclass. `test_capability_cannot_upgrade_spec` and
`test_missing_binary_is_not_reported_as_ready` enforce this.

**Alternatives rejected.** Trusting the spec (produces fake-ready rows); probing
synchronously on every access (unusable UI).

---

## D-004 — Provider discovery reports failures instead of swallowing them

**Date:** 2026-09-15 · **Status:** accepted

**Context.** `discover_builtins()` wrapped each import in `try/except ... log.warning`.
A single failing module import left the registry short, silently removing an
entire provider domain. This surfaced as 21 test failures with no error message
anywhere — the diagnostic cost far exceeded the robustness gained.

**Decision.** Record failures in a module-level `_LOAD_FAILURES` map, log them at
error level, expose them through `load_failures()`, and guard the one-time import
with an explicit `_LOADED` flag rather than `if not _REGISTRY`.

**Consequences.** A broken optional provider still cannot take down the registry
(the original goal), but the failure is now visible and testable. The `_LOADED`
flag also fixes a latent bug: because the provider modules are plain `import`s,
Python caches them, so any logic that re-ran discovery after a `clear()` would
never re-trigger the `@register` decorators and the registry would stay empty
forever.

**Alternatives rejected.** Re-raising (one broken optional provider breaks the
whole app); an empty `except: pass` (the bug that caused this record).

---

## D-005 — Heavy state lives outside the repository, on the data drive

**Date:** 2026-09-15 · **Status:** accepted

**Context.** The OS drive had ~8 GB free; the data drive had ~53 GB. Caching
video work product and Python environments inside the repo would fill it.

**Decision.** All heavy state goes under a single resolved home:
`D:\html-video-workflow` (or `E:`) when that drive exists, otherwise
`~/.html-video-workflow`. `HVW_HOME` overrides it. The env value is normalised so
`/d/x`, `D:\x` and `D:/x` all resolve identically, and a *relative* value raises
rather than silently creating a directory named `\d\x` inside the repo.

**Consequences.** The repository stays small and cloneable. The layout is
discoverable from one function (`config/paths.py`), and `html-video doctor`
prints the resolved home on every run so a surprise is immediately visible.

**Alternatives rejected.** Repo-local storage (fills the OS drive); hardcoding
`D:` (breaks on machines without it).

---

## D-006 — Fallbacks are explicit and always recorded

**Date:** 2026-09-14 · **Status:** accepted

**Context.** A render must not fail because a browser disappeared, but it also
must not silently produce mock output that looks like a real render.

**Decision.** Declare fallback chains per stage (`tts`, `renderer`, `llm`,
`subtitle`). On a typed provider failure, advance along the chain and append
`{stage, from, to, reason}` to `job.fallbacks`. The job manifest is the record of
what actually happened.

**Consequences.** A degraded run still completes, and the degradation is
auditable after the fact — the QC report and the manifest both name the real
provider. `test_render_stage_falls_back_when_browser_missing` asserts the chain
entry exists and that `job.plan.renderer` is updated to what really ran.

**Alternatives rejected.** Hard-failing (a missing browser should not lose a
finished narration); silent substitution (indistinguishable from a real render).

---

## D-007 — Presets, not model names

**Date:** 2026-09-14 · **Status:** accepted

**Context.** Asking users to pick between `fish_speech`, `cosyvoice` and `moss`
requires knowledge they should not need, and produces choices that are wrong on
their hardware.

**Decision.** The user picks a preset (`auto`, `fast`, `balanced`,
`high_quality`, `max_quality`). The planner scores every candidate against
hardware, language, licence, VRAM budget (85% of total) and recorded benchmarks,
then explains the choice in a `reason[]` list. `auto` reads real VRAM/RAM.

**Consequences.** Routing is data-driven and re-tunes as benchmarks accumulate.
Hard filters (unavailable, unsupported language, VRAM over budget) exclude a
candidate before scoring, with the exclusion reason recorded — so a rejection is
never mysterious.

**Alternatives rejected.** A fixed default provider (wrong on most machines); a
manual provider picker as the primary UI (power-user escape hatch only).

---

## D-008 — Neural TTS engines are HTTP sidecars, never pip dependencies

**Date:** 2026-09-15 · **Status:** accepted

**Context.** Fish Speech, CosyVoice and their peers ship as Python projects with
`torch`, CUDA expectations and multi-gigabyte model weights. Adding them as
dependencies would mean every `pip install` of this project either downloads
gigabytes or fails — and would make the *core* unimportable on a machine with no
GPU, which is exactly the machine CI and most contributors have.

**Decision.** Neural engines are reached over HTTP
(`GET /health`, `GET /v1/voices`, `POST /v1/tts`). `providers/tts/neural_sidecar.py`
is a *class-level* adapter covering the common shape shared by self-hosted
servers. **The core keeps only `pydantic` and `python-dotenv`.**

**Consequences.** The user must run an engine separately, and this projects gains
a process-boundary failure mode to handle — which we do: no URL ⇒
`not_installed`, unhealthy `/health` ⇒ `unavailable`, 502/503/504 ⇒
`ProviderTimeout`. In exchange, a laptop without CUDA can still run the whole
test suite, and CI never downloads a model.

**Alternatives rejected.** Vendoring the engines (unusable core on weak
machines); a separate optional extras group holding `torch` in-process (same
result, worse isolation); skipping neural TTS until a GPU exists (would leave the
routing table and Studio missing their key row, and nothing wired to receive the
engine when it arrives).

---

## D-009 — Capability claims are tri-state, not boolean

**Date:** 2026-09-15 · **Status:** accepted

**Context.** A boolean `supports_emotion` gives a provider two choices: claim
support before it has been probed, or deny a feature it actually has. Both are
lies, and the router consumes whichever lie is told.

**Decision.** Capabilities are `yes` / `no` / `unknown` via `CapabilityFlag`, and
only `yes` is truthy. An unmapped field is reported `no`, never `yes` — even when
most implementations of that API would accept it. `neural_sidecar` claims `yes`
for features its *class* of engine promises, and the docs say plainly that this
is a claim awaiting a probe.

**Consequences.** Routing is slightly conservative: an engine that supports a
feature but has not declared it scores lower than one that has. That is the
correct direction to be wrong in — under-claiming routes elsewhere, while
over-claiming silently drops the user's request.

**Alternatives rejected.** Booleans with optimistic defaults; `Optional[bool]`,
where `None` is easily conflated with `False` at every call site.

---

## D-010 — Presets carry a fidelity penalty so placeholders cannot win

**Date:** 2026-09-15 · **Status:** accepted

**Context.** `mock_tts` declares `speed_score=10` because it is instant. That
single field let it out-score every real engine, so `high_quality` — the preset a
user picks when they want the best narration — routed to a placeholder tone.
The pipeline reported success. Nothing was visibly broken.

**Decision.** Providers that are placeholders rather than engines carry a
`low_fidelity` spec tag. Each preset adds a `fidelity_penalty` weight: `0` under
`fast`, rising to `4` under `max_quality`. Penalised providers stay in the pool
and say so in `reason[]`.

**Consequences.** `fast` still legitimately selects the mock — speed really is the
point there — while quality presets select a real engine. Mocks remain the
guaranteed last resort that keeps the pipeline alive on a bare machine. An extra
weight joins the tuning surface.

**Alternatives rejected.** Hard-excluding mocks (strands machines with no
engine); lowering their speed score (a lie in the other direction, and it would
break `fast`); letting the router sort by quality only (discards legitimate
speed/latency trade-offs).

---

## D-011 — Prosody v1 is rule-based, not model-based

**Date:** 2026-09-15 · **Status:** accepted

**Context.** Pause placement, emphasis and pacing could be produced by an LLM.
That would add a network dependency, a cost per render, and non-determinism to
the one stage CI needs to test cheaply.

**Decision.** `pipeline/prosody.py` is deterministic rules over punctuation:
terminal marks (`。` 420 ms, `？` 430, `！` 400…), soft marks (`，` 170, `、` 110…),
clause subdivision past a character threshold, and emphasis for modal words.
Every segment carries a `rationale` explaining why it looks like it does.

**Consequences.** Fully testable offline — 27 tests including determinism — and a
wrong pause is *debuggable* from its rationale. It will not capture discourse
structure the way a model could; that is acceptable for v1, and the plan format
is designed so an LLM planner can produce the same structure later.

**Alternatives rejected.** LLM-planned prosody in v1 (not testable in CI, costs
money per render, non-reproducible); hand-tuned per-scene SSML in the IR (leaks
rendering detail into the model — forbidden by D-002).
