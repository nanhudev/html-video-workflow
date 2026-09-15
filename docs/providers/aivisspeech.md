# AivisSpeech TTS (`aivisspeech`)

HTTP adapter for AivisSpeech / VOICEVOX-compatible engines.

> **REAL HARDWARE VALIDATION PENDING.**
> Request mapping, pause placement and emphasis are covered by tests against a
> **real local HTTP stub server** (`tests/test_tts_providers.py`). No actual
> AivisSpeech engine has been run against this adapter, because doing so needs
> the engine and its model on disk. Nothing here claims the audio sounds good.

| | |
| --- | --- |
| Implementation | HTTP sidecar |
| Local | yes (runs on 127.0.0.1) |
| Quality tier | `high` |
| GPU | `optional` |
| Model download | owned by the engine, not by this adapter |

## Rationale: why a sidecar and not a pip dependency

The engine is a Python project with its own (heavy) model, dependencies and CUDA
expectations. Vendoring it would put `torch` in our dependency tree and make
every install a multi-gigabyte gamble. Instead we speak HTTP to whichever port
the user already runs the engine on.

**The core therefore has no `torch`, `transformers` or CUDA dependency — and
never will while this design holds.**

## Protocol

| Endpoint | Purpose |
| --- | --- |
| `GET /speakers` | list selectable voices |
| `GET /engine_manifest` | engine metadata (treated as optional) |
| `POST /audio_query` | text → acoustic query JSON |
| `POST /synthesis?speaker=N` | query → WAV bytes |

Synthesis is therefore always **two** calls. A single-call shortcut does not
exist in this protocol, and pretending otherwise would break on every engine.

## Configuration

| Variable | Default |
| --- | --- |
| `HVW_AIVIS_BASE_URL` | `http://127.0.0.1:10101` |
| `HVW_AIVIS_SPEAKER` | `888753760` |
| `HVW_AIVIS_TIMEOUT` | see http client default |

## Capabilities

| Feature | Support | Note |
| --- | --- | --- |
| emotion | `no` | mapped nothing; reported honestly |
| style | `yes` | via speaker/style id |
| voice clone | `unknown` | depends on the engine build |
| speed | `yes` | `speedScale` |
| pitch | `yes` | `pitchScale` on moras |
| emphasis | `yes` | raises `pitchScale` on matching moras |
| streaming | `yes` | per-query streaming is available |
| SSML | `no` | this protocol has no SSML |

## How emphasis works

The engine works in *moras*, not words. `_apply_emphasis()` finds characters that
belong to an emphasised substring and raises their mora pitch. Text that does not
match any emphasis target is left untouched — so an emphasis cue that cannot be
located degrades to "read it normally", never to "read it wrong".

## Failure behaviour

An unreachable engine returns `UNAVAILABLE` and **never raises**. A probe must
not be able to take down a job; it must be able to *answer* a job.

## Running it for real

1. Start AivisSpeech so it listens on `HVW_AIVIS_BASE_URL`.
2. `html-video providers` — `aivisspeech` becomes available.
3. Route to it explicitly to confirm the mapping end to end:
   `html-video create "..." --preset high_quality --tts aivisspeech`
4. Record what you actually heard in `docs/CURRENT_STATUS.md`. Until someone
   does step 4, this provider stays marked hardware-unvalidated.
