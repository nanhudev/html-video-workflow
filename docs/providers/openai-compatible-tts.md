# OpenAI-compatible TTS (`openai_compatible_tts`)

HTTP adapter for any endpoint exposing OpenAI's `POST /audio/speech` shape.

> **REAL HARDWARE VALIDATION PENDING.**
> Verified against a local stub server, not against OpenAI or another vendor.
> No key is required to run the tests, and none is used by CI.

| | |
| --- | --- |
| Implementation | remote API |
| Local | **no** |
| Quality tier | `high` |
| GPU | `no` |
| Model download | n/a |

## Configuration

| Variable | Default |
| --- | --- |
| `HVW_TTS_API_KEY` / `OPENAI_API_KEY` | — (required) |
| `HVW_TTS_BASE_URL` | OpenAI default |
| `HVW_TTS_MODEL` | provider default |
| `HVW_TTS_VOICE` | provider default |
| `HVW_TTS_TIMEOUT` | see http client default |

Absent key ⇒ probe reports `missing_credentials`, **not** an error. "You did not
give me a key" and "your key is broken" are different failures and must stay
different.

## Capabilities

| Feature | Support |
| --- | --- |
| emotion | `no` |
| style | `unknown` |
| voice clone | `unknown` |
| speed | `no` |
| pitch | `no` |
| emphasis | `no` |
| streaming | `yes` |
| SSML | `no` |

Note `supports_speed = no` even though most OpenAI-compatible endpoints accept a
`speed` parameter. This adapter does not yet map `TTSRequest.speed`, and **an
unmapped field is reported `no`, never `yes`.** A capability that claims more
than the code does is worse than a missing one.

`style` and `voice_clone` are `unknown` because they depend entirely on which
server sits behind the URL — claiming either would be guessing about someone
else's software.

## Secret discipline

This is the strictest part of the adapter, because an API key leak is not
recoverable.

- The key is read **from the environment only**. Never from project or job files.
- It travels as an **`Authorization` header**, never as a query string. Query
  strings get logged by proxies, browsers and shell history.
- Logging goes through `_redact()`, which strips query strings before anything
  is written.
- What may be printed is `masked_key` — always safe, always renders as
  something like `sk-****890`. A missing key yields a masked form too, so
  there is no code path that can accidentally print a real one.
- Keys never enter `job.json`, `events.jsonl` or any artifact.

## Retry policy

**Only idempotent requests retry.** `GET` yes; `POST /audio/speech` no.

Retrying a synthesis POST on a timeout is how you pay for the same sentence
twice. A 429 is deliberately *not* retried — it is mapped to
`ProviderTimeout`, which lets the runtime fall back instead of hammering a
service that just asked us to slow down.
