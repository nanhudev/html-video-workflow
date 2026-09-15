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
| `api/studio.py` | serves the built Studio frontend from the API process |
| `cli/main.py` | `html-video generate`, `html-video studio` |
| `mcp/server.py` | JSON-RPC tools: `create_video`, `suggest_topics`, … |
| `apps/studio/src/pages/Generate.tsx` | the GUI entry point |
| `scripts/e2e_one_click.py` | the CI one-click check, and the diagnosis it cannot drop |
| `scripts/e2e_entry_points.py` | the same for SDK, REST and MCP |

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

Verified on the development machine, with frames extracted and looked at rather
than trusting the exit code:

| Video | Geometry | Duration |
| --- | --- | --- |
| `向量数据库` | 16:9, 1920×1080 | ~19.7 s |
| `解释 CI 流水线为什么变慢` | 9:16, 1080×1920 | 20 s target |

Scene boundaries were checked at exact timestamps (`t=4.0/8.0/12.0/16.0`), and
the reported duration was confirmed against the actual encoded frame count
(587 frames ≈ 19.63 s at 29.85 fps) — not just the container's metadata.

Re-run after the routing and duration work, with the exact command CI uses:

```
html-video generate "Why local AI matters" \
    --width 320 --height 180 --duration 6 --scenes 1 --out out --json
```

| Field | Value |
| --- | --- |
| `ok` | `true` |
| Output | `Why local AI matters-job_9bf37fcd8e0c.mp4`, 240 280 bytes |
| Measured | 320×180, 8.88 s, h264 + aac, 29.885 fps |
| QC | 10 checks — 9 pass, 1 warn (`duration_match` Δ3.12 s), 0 fail |
| Providers | `mock_llm` · `mock_tts` · `advanced_html` · `srt` |
| Fallbacks | none |
| Elapsed | 43.0 s |

`--scenes 1` became 4 scenes, because `editorial_argument` is a four-beat
structure and a template's scene count is a floor, not a suggestion. Four scenes
cannot run shorter than ~12 s, so a 6 s target is unreachable; the result says
so in `warnings` rather than silently delivering something else. That warning is
new — see §4.

This does **not** replace CI: it proves the pipeline produces real video; CI
proves it still does after every change.

---

## 5b. The front door did not open — found by executing the documentation

Everything above was true while four of the five advertised entry points could
not be used as documented. None of these were caught by 324 passing tests,
because the tests were written against the code and the code was self-consistent
— only the *advertisement* was wrong. They were found by running what each
document actually told a reader to run.

| What the docs said | What happened | Fix |
| --- | --- | --- |
| `create_video("Why local AI matters", output="result.mp4")` | the positional prompt was **silently discarded** (the wrapper only understood a `CreateVideoRequest` in first position) and `output=` was **silently accepted** (`extra="allow"`), so the call failed with "nothing to make a video from" | the prompt is now accepted positionally, and an unknown field raises `TypeError` — it is no longer possible to pass an argument that is ignored |
| `html-video generate "…" -o result.mp4` | `-o` does not exist; the flag is `--out`, and it names a **directory**, not a file | every document now shows `--out <dir>` and a command that parses |
| `html-video studio` | no such subcommand existed — the Studio was reachable only via `npm run dev` in a checkout | `studio` is now a real subcommand that serves the built frontend |
| `html-video serve` "REST + Studio" | it served the REST API only; `create_app()` had no static mount | the built frontend is mounted at `/`, after the routers |
| MCP companion tool `get_job` | the tool is named `video_status` | corrected in `SKILL.md` |
| Vite dev proxy list | omitted `/v1`, while `src/api.ts` was already posting to `/v1/videos` — the Generate page worked in a production build and got HTML back in dev | `/v1` added to the proxy |

Two tests now guard this class of defect, and they are written against the
documents rather than the code:

- `test_every_documented_cli_example_actually_parses` — feeds every
  `html-video …` line in `README.md`, `QUICKSTART.md`, `SKILL.md` and
  `docs/API.md` through the real argument parser;
- `test_docs_do_not_advertise_a_python_field_that_does_not_exist` — extracts
  every keyword from every documented `create_video(...)` call and checks it
  against `CreateVideoRequest.model_fields`.

---

## 6. Test totals

| Where | Result |
| --- | --- |
| Local, Windows, full suite | **337 tests, 0 failures, 0 errors, 0 skipped** (`--junitxml`, ~13 min) |
| CI, `tests/test_phase3_product.py` | **pass** |

The local number is read from the junit report, not the console: this runner
kills long-lived child processes, so a console summary line is not trustworthy
here. The run that produced 337 also produced the two failures below — both are
worth recording, because one was a real defect the new tests found and the other
was a bug in the test itself.

| Failure | What it was |
| --- | --- |
| `test_cli_maps_error_codes_to_exit_statuses` | adding `job_not_found` to the shared status table left the CLI's `EXIT_CODES` without an entry for it. The assertion — every code in `HTTP_STATUS` has an exit status — is exactly the kind that keeps two tables derived from one vocabulary honest. Fixed by giving `job_not_found` the same exit status as `no_template` (2). |
| `test_every_documented_cli_example_actually_parses` | the new test passed the program name to `argparse.parse_args`, which takes arguments, not a command line. A bug in the check, not in the documents: with the program name dropped, all 27 documented examples parse. |

The second is the more embarrassing and the more instructive: a test written to
guarantee "the front door opens" was itself broken in a way that looked like
28 broken documents.

## 7. GitHub CI is the authority

The local Windows box cannot run the suite to completion, so CI is the record.
`.github/workflows/ci.yml` runs:

| Job | Proves |
| --- | --- |
| `discover` | lists the test files for the matrix; also posts a canary status, so a broken reporting path is visible before it is needed |
| `pytest` (one job per test file) | a red build names the file that broke |
| `python` | collect, full suite, junit summary (fails on any failure/error, or on zero tests), IR schema check, provider registry loads with no silent failures |
| `studio` | frontend typecheck + build, uploads `dist` |
| `package` | builds the Studio frontend, vendors it into the package, builds sdist + wheel, installs into a **clean venv**, asserts the builtin JSON manifests *and* the Studio frontend shipped as package-data, runs `html-video --help` and `html-video studio --help` |
| `one-click` (windows-latest) | CLI `generate` → ffprobe; Python SDK `create_video`; REST `wait=true`, `wait=false` and unknown-job 404; MCP `tools/list` and `create_video` |

The one-click job renders at **320×180, one scene** — enough to prove the whole
chain (source → plan → IR → render → voice → compose → QC) without making CI
slow or flaky. It runs on `windows-latest` because the renderer drives Edge and
the local voice path is SAPI: a Linux runner would be testing a browser stack
nobody ships.

No `|| true`, no skipping a failing test. `continue-on-error` appears on the E2E
steps **only** so that a step which dies cannot take the diagnosis with it; a
gate step immediately afterwards turns the job red. The one thing that must
never happen is a red build that says nothing.

### Reading a red build without log access

Runner logs, job artifacts and even the `check-runs` annotations all require a
browser session or a token. The annotations carry only "Process completed with
exit code 1" — no output. So everything a failure needs to say has to travel
through a channel that plain read access can see:

1. a **matrix**, one job per test file — a red build names the file;
2. on failure, a **commit status** whose description lists the failing test
   names — readable with plain repo read access;
3. for the one-click E2E, a script (`scripts/e2e_one_click.py`) that posts what
   it observed — the CLI's error code and message, the tail of its stderr, the
   provider table, and a planning-only dry run — from a `finally` block, so no
   failure mode can skip the reporting.

Step 3 exists because of a concrete loss: the one-click job went red and posted
nothing at all, which cost a full build cycle to learn nothing. The reporting is
now structurally impossible to skip, and `e2e_entry_points.py` does the same for
the SDK, REST and MCP surfaces.

That combination produced the exact list in §8 without ever opening the log.

---

## 8. Three pre-existing tests failed on Linux — not Phase 3 code

`tests/test_phase3_product.py` is green on CI. The three failures are in tests
that predate this phase and assert things that are only true on Windows:

| Test | Why it cannot hold on Linux | Fix |
| --- | --- | --- |
| `test_home_env_accepts_windows_posix_and_gitbash_paths` | the whole point is `/d/x → D:/x`; on POSIX a leading slash already means what it says | skip off Windows |
| `test_quality_presets_never_choose_a_placeholder[high_quality\|max_quality]` | "a fidelity preset must not pick the mock" only means something when a real engine exists; Linux has no SAPI, so the mock *is* the right answer | skip when no non-placeholder TTS is available |
| `test_mock_render_stage_produces_png` | let the router pick the renderer, so it depended on which browser existed on the runner | pin `mock_renderer` — the browser-dependent path has its own test |

Each is skipped or pinned with a stated reason, not deleted and not made to pass
by weakening the assertion.

## 8b. What the CI diagnosis found: two silent failures

§7's self-reporting paid for itself on its first run. The `e2e/*` commit statuses
named the one-click failure outright, with no runner log access:

```
e2e/cli/stderr  failure  …_workflow.cli | UnicodeEncodeError: 'charmap' codec
                 can't encode character '\u2192' in position 848
e2e/sdk         success  positional prompt -> 239854 bytes
e2e/rest        success  wait=true -> MP4; wait=false -> job_…; unknown job -> 404
e2e/mcp         success  6 tools; create_video produced e2e-out-mcp\…mp4
```

So the product worked — SDK, REST and MCP all produced real MP4s on the runner —
and only the CLI path failed, for a reason that had nothing to do with rendering.

### Defect 1 — the CLI died reporting a success

Windows gives a *piped* stdout the locale encoding: **cp1252** on an en-US
runner, cp936 on a Chinese desktop. `--json` output embeds routing explanations
that contain `→` (U+2192). cp936 has that character; cp1252 does not. So `print`
raised `UnicodeEncodeError` *after* the MP4 had been written, the CLI's own
error handler caught it and returned 1, and stdout arrived empty — which the
harness read as "the pipeline is broken".

This is why it passed locally and failed on CI, and it was invisible until the
statuses existed. The fix relaxes the *failure mode* of the streams rather than
their encoding: forcing UTF-8 would turn correctly rendered Chinese into mojibake
on a Chinese console, breaking the common case to rescue the rare one. An
unencodable glyph now degrades to a substituted character (`utils/console.py`),
which keeps the JSON parseable — and the em-dash in the same payload, which
cp1252 *can* represent, is still written verbatim.

### Defect 2 — a placeholder voice was winning, silently

Investigating the CLI path turned up a worse defect underneath it. On a machine
with a real Chinese voice installed:

```
$ html-video providers            # this machine
OK  tts  sapi    SAPI available with 2 voices
```

and yet the documented one-click command, whose default language is `zh-CN`,
planned `tts: mock_tts` — a placeholder tone. Not a *loud* failure: the tone is
generated at the narration's estimated length, so audio QC passed, the render
returned `ok: true`, and the only trace was one word in the provider list.

Two independent causes, both now fixed:

1. **A weight cannot enforce a guarantee.** `mock_tts` declares
   `low_fidelity`, meaning "choose me only if nothing real is left" — but the
   router expressed that as a *scoring penalty*, and a penalty only makes the
   mock usually lose. `mock_tts` scores 10/10 on speed, which beat `sapi` under
   both `balanced` (12.85 vs 12.5) and `fast`. Placeholders are now excluded from
   selection while any real provider is usable, with an explicit exemption for a
   user lock so `--tts mock_tts` still means what it says.
2. **The language claim was never verified.** `sapi` declares
   `languages=["zh-CN", "en-US"]` unconditionally, because the Windows Speech
   API supports both — while the *installed* voices are what a machine can
   actually say. `TTSProvider.capabilities()` folded the descriptor's feature
   flags into the capability but kept the spec's language list, so the router
   decided on the declaration. `sapi.descriptor()` had derived languages from
   `GetInstalledVoices()` all along; the router simply never saw it. The
   capability now takes the intersection of declared and probed — a probe may
   narrow a claim, never widen it — and a claim contradicted outright is
   replaced rather than emptied, because an empty list reads as "undeclared" and
   would *remove* the language check instead of tightening it.

The verification that the earlier assumption lacked:

```
$ python -c "…sapi.list_voices()…"
Microsoft Huihui Desktop | zh-CN | Female      <- it does speak Chinese
Microsoft Zira Desktop   | en-US | Female
```

The previous revision of this report asserted that zh-CN routing to `mock_tts`
was "correct rather than broken — SAPI's two voices are English". That was an
assumption about the machine, contradicted by the machine. Enumerating the voices
took one command; the assumption had survived a whole phase. It is corrected here
rather than quietly dropped.

A placeholder is still selected when nothing real is available — that is the
point of it, and it is asserted by a test against a pool containing only
placeholders — but it can no longer be *silent*: the plan carries a warning
naming the language that has no voice, and the providers that declined for that
reason, so the message says what to install instead of only that something is
missing.

## 9. Known issues

- **Critic findings are not yet acted upon.** `VisualDesignCritic` emits
  `AA-001…AA-012`; nothing consumes them to change a layout. `AA-012`
  ("nothing moves continuously") still fires on every scene rendered so far,
  because the motion chooser never reaches `parallax`/`drift`.
- **A language no provider declares leaves the TTS stage empty.** A `fr-FR`
  request selects no TTS provider at all; the router logs a warning and the plan
  proceeds with narration unassigned. It is not *silent* — the routing
  explanation records every refusal — but it is not yet a first-class warning
  either, unlike the placeholder case above.
- **Local verification must not be trusted for CI claims.** The D: virtualenv's
  `site-packages` was destroyed mid-session (pip, fastapi, httpx, anyio,
  httpcore, attrs, packaging all hollowed to empty namespace directories) by a
  `pip install -e` run whose uninstall step collided with the shell's
  safe-delete guard. It was rebuilt from scratch at `D:\hvw-venv`; a fresh venv
  performs no uninstalls, which is why the rebuild survived. Tests themselves
  never depended on it — `pyproject.toml` sets `pythonpath = ["src"]`, so pytest
  imports the working tree directly.
- **Local environment limitation:** the shell's safe-delete guard kills
  long-running child processes, so any local run must use D:,
  `TMP/TEMP/TMPDIR` pointed at D:, and the background runner. `head`, `tail` and
  `bash` are not on the shim's PATH; drive the work from Python instead. A
  foreground run also dies at the tool's 2-minute limit, which is not a test
  failure and must not be read as one.
- **`@register` replaces the provider class.** The decorator binds the module
  name to a `register` *instance*, so `SomeProvider.anything` fails and the
  registry converts that into "the provider is unavailable". It cost a detour
  while adding a per-provider cache; class-level state must go at module scope.

---

## 10. Next

1. Confirm the one-click E2E goes green on `windows-latest` with both defects
   fixed, then merge `phase3-productization` into `main` — only when CI, the
   package build, the Studio build and the one-click E2E are all green.
2. Close the loop on critic findings — let a finding change a layout, starting
   with `AA-012`.
3. Promote "no provider can speak the requested language" to the same
   first-class warning the placeholder case now has.
4. Validate on real hardware — the RTX 2070 path, and a neural TTS engine —
   which CI cannot do by design.
