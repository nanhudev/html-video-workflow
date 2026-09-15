# PHASE 3 — One-click Productization

**Goal:** one prompt in, one complete MP4 out — through any entry point, with
one implementation behind all of them.

```
CLI  ─┐
SDK  ─┼──▶  CreateVideoRequest  ──▶  VideoRuntime.create_video()  ──▶  VideoResult
REST ─┤
MCP  ─┘         (plus the Studio GUI, which calls the same method)
```

---

## 1. What was built

| Module | Purpose |
| --- | --- |
| `core/request.py` | `CreateVideoRequest`, `VideoResult`, platform presets, `SourceInput` |
| `core/errors.py` | `VideoErrorCode` + one HTTP-status/exit-code table |
| `sources/` | WebPage / GitHub / Markdown / LocalFile / Text → `SourceDocument[]` |
| `planning/topic_planner.py` | prompt → clean topic + ranked angles, offline |
| `planning/script.py` | topic → narration beats, duration-aware |
| `planning/storyboard.py` | beats → IR V2 scenes |
| `planning/pipeline_planner.py` | the whole decision chain, with a `reason` per step |
| `templates/` | 7 manifests + 6 style profiles, hard-filter-then-score ranker |
| `runtime/engine.py` | `VideoRuntime.create_video()` — the single implementation |
| `api/routes/v1.py` | `POST /v1/videos`, catalogue, jobs, topics |
| `cli/main.py` | `html-video generate` |
| `mcp/server.py` | JSON-RPC tools: `create_video`, `suggest_topics`, … |
| `apps/studio/src/pages/Generate.tsx` | the GUI entry point |

Template and style are deliberately separate: the template is the *structure of
the argument*, the style is the *skin*. A template declares what it needs
(`requires: ["data"]`, supported aspects, scene range); the ranker applies hard
filters first so a template that cannot run is never rescued by a good score.

---

## 2. Recovering the uncommitted work

The branch was created from a working tree that had never been committed. It is
now `phase3-productization`, built on `4c671a9` (Phase 2), with the full
Phase 3 diff preserved — 8 modified and 29 new files, nothing dropped, nothing
reset:

```
24a69b2  WIP: PHASE 3 one-click productization   (the recovered work)
5a6f831  Fix 7 real Phase 3 test failures
...
```

---

## 3. The "4 failing tests" were 7

The earlier count was wrong because the runner never reached the end. `pytest`
was being **SIGTERM'd at test 32** — the console showed
`.F......F..FF...................` and stopped, so no junit file and no summary
was ever written, and three failures that live further down the file were
invisible.

Running the file to completion (in the background, so the tool's own timeout
could not kill it) surfaced **seven**:

| # | Test | Verdict |
| --- | --- | --- |
| 1 | `test_an_empty_request_is_rejected` | **code bug** — fixed |
| 2 | `test_markdown_source_keeps_structure` | **code bug** — fixed |
| 3 | `test_source_truncation_is_reported` | **code bug** — fixed |
| 4 | `test_missing_file_source_raises_…` | **code bug** — fixed |
| 5 | `test_shrinking_a_script_keeps_the_opening_and_the_ending` | **test bug** — fixed |
| 6 | `test_v1_unknown_template_is_a_404` | **code bug** — fixed |
| 7 | `test_all_entry_points_share_the_runtime_method` | **test bug** — fixed |

### Code bugs

**Whitespace-only intent was accepted.** `_require_intent` used
`if not any((self.prompt, ...))`, and `"   "` is truthy in Python, so a blank
prompt reached the planner and produced a video about nothing. Intent is
semantic; a string of spaces carries none. Now normalised in a field validator,
with regressions for `""`, `"   "`, `"\n"`, `"\t"`, `"\r\n"`.

**`resolve_source()` refused the shape its own API documents.** Callers pass
`{"kind": "text", "value": ...}`; the runtime only accepted a `SourceInput`. The
public boundary now accepts a mapping and normalises it. Related: `kind` was
being read as "go fetch this", so inline markdown content was treated as a path.
`kind` now describes what `value` **is** — a path only when one exists.

**Unknown template returned 422.** A named template that does not exist is a
missing resource, not an unprocessable request; 422 is reserved for input that
cannot be validated. Now 404.

**Two speech-rate estimators.** The planner counted characters while the audio
stage measures speech seconds (`estimate_speech_seconds`, which ignores
whitespace) — English scenes came out ~14% long. There is now one canonical
estimator, and narration is trimmed against a *seconds* budget by binary search
rather than a proportional character cut.

**A duration target the material cannot fill was silently missed.** Trimming can
only shorten. Asking for 45 s from material that supports 38 s returned 38 s
with no explanation. Padding the gap with held frames would just be dead air, so
the shortfall is now reported in `warnings`.

### Test bugs (wrong expectations, not wrong code)

- `test_shrinking_a_script_…` asked `documentary_walkthrough` for 4 scenes; that
  template declares `min: 6`, so clamping to 6 is correct. The test now asks for
  a count inside the declared range and asserts what it actually cares about —
  which beats survive the trim.
- `test_all_entry_points_…` did `from html_video_workflow.cli import main`, which
  yields the re-exported **function**, not the module, so `getsource` only ever
  saw argparse plumbing. Now imported with `importlib`.

Neither production behaviour was changed to make a bad test pass.

---

## 4. The duration contract

`duration_sec` is a **target**, honoured within ±10% where the material allows.

```
target duration → narration budget → narration length → scene timing
```

Timing is downstream of the words. The original bug rescaled scene timings to
make the numbers add up while the narration stayed just as long — the audio
stage measures the text, so a "20 second" video came out 32 seconds. Both
directions are now covered by tests:

- too long → narration trimmed, `warning` recorded
- too short → cannot be padded with dead air, so the shortfall is reported and
  the real number returned

---

## 5. Real MP4 — LOCAL E2E VERIFIED

Verified on the development machine before the environment became unusable, with
frames extracted and looked at rather than trusting the exit code:

| Video | Geometry | Duration |
| --- | --- | --- |
| `向量数据库` | 16:9, 1920×1080 | ~19.7 s |
| `解释 CI 流水线为什么变慢` | 9:16, 1080×1920 | 20 s target |

Scene boundaries were checked at exact timestamps (`t=4.0/8.0/12.0/16.0`), and
the reported duration was confirmed against the actual encoded frame count
(587 frames ≈ 19.63 s at 29.85 fps) — not just the container's metadata.

This does **not** replace CI: it proves the pipeline produces real video; CI
proves it still does after every change.

---

## 6. GitHub CI is the authority

The local Windows box cannot run the suite to completion, so CI is the record.
`.github/workflows/ci.yml` runs:

| Job | Proves |
| --- | --- |
| `python` | collect, full suite, junit summary (fails on any failure/error, or on zero tests), IR schema check, provider registry loads with no silent failures |
| `studio` | frontend typecheck + build, uploads `dist` |
| `package` | builds sdist + wheel, installs into a **clean venv**, asserts the builtin JSON manifests shipped as package-data, runs `html-video --help` |
| `one-click` | CLI `generate` → ffprobe; Python SDK `create_video`; REST `wait=true` and `wait=false`; MCP `tools/list` and `create_video` present |

The one-click job renders at **320×180, one scene** — enough to prove the whole
chain (source → plan → IR → render → voice → compose → QC) without making CI
slow or flaky.

No `|| true`, no `continue-on-error`, no skipping a failing test. A red step
means a real defect.

---

## 7. Known issues

- **`GET /v1/videos/{unknown}` returns 422** while `GET /v1/templates/{unknown}`
  returns 404. Both are "the named thing is not there" and should agree; the
  template case was the one under test, so the job case was left alone rather
  than changed without a decision. Recommended: 404 for both.
- **Critic findings are not yet acted upon.** `VisualDesignCritic` emits
  `AA-001…AA-012`; nothing consumes them to change a layout. `AA-012`
  ("nothing moves continuously") still fires on every scene.
- **Frontend build is CI-only locally.** `apps/studio/node_modules` was not
  migrated to the D: workspace, so `npm run typecheck` cannot be run here;
  CI covers it.
- **Local environment limitation:** C: has ~0–4.7 GB free and the shell's
  safe-delete guard kills long-running child processes. Any local run must use
  D:, `TMP/TEMP/TMPDIR` pointed at D:, and the background runner.

---

## 8. Next

1. Get the CI `python` job green (see §7 for the platform-sensitive suspects).
2. Merge `phase3-productization` into `main` only when CI, package build and
   one-click E2E are all green.
3. Reconcile the 404/422 inconsistency.
4. Close the loop on critic findings — let a finding change a layout.
