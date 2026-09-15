# Neural TTS sidecar (`neural_sidecar`)

**Class-level adapter** for Fish Speech / CosyVoice-style engines reached over
HTTP.

> **REAL HARDWARE VALIDATION PENDING — this is the least validated provider in
> the codebase.**
> The adapter is written, registered, probed and *tested against a local stub*,
> but **no neural engine has ever answered it.** No model was downloaded
> (deliberately). Treat its capabilities as claims awaiting a check.

| | |
| --- | --- |
| Implementation | HTTP sidecar |
| Local | yes |
| Quality tier | `studio` |
| GPU | `optional` |
| Model download | none by this package |

## Why it exists before it has been validated

The Phase 1 brief required an advanced neural adapter **without** downloading
models. The honest way to do that is to write everything except the engine:

- probe / config / health check
- request mapping and response handling
- error classification
- tests against a stub

…and then say plainly that the last mile is unverified. Removing the adapter
until GPUs arrive would be worse: the routing table, the fallback chains and the
Studio's provider view would all be missing their most important row, and the day
someone plugs in a real engine nothing would be wired to receive it.

A tier of `studio` is a **claim**, not a measurement. Per the spec→probe→capability
model, a probe may confirm or downgrade a claim but may never upgrade one.

## Protocol

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | liveness; the only way availability is decided |
| `GET /v1/voices` | optional voice list |
| `POST /v1/tts` | synthesis request → audio bytes |

This is the common shape shared by self-hosted neural servers, which is why one
adapter covers several engines rather than one engine each.

## Configuration

| Variable | Default |
| --- | --- |
| `HVW_NEURAL_TTS_URL` | — (**required**; absence ⇒ `not_installed`) |
| `HVW_NEURAL_TTS_ENGINE` | `auto` (`fish_speech` / `cosyvoice`) |
| `HVW_NEURAL_TTS_VOICE` | — |
| `HVW_NEURAL_TTS_TIMEOUT` | see http client default |

Without a URL the provider reports **`not_installed`**, not `unavailable`. Those
differ in what the user should do about them: not-installed means "configure
it", unavailable means "it is configured but not answering".

## Capabilities (claimed)

| Feature | Support |
| --- | --- |
| emotion | `yes` |
| style | `yes` |
| voice clone | `yes` |
| speed | `yes` |
| pitch | `unknown` |
| emphasis | `unknown` |
| streaming | `yes` |
| SSML | `unknown` |

`yes` here means "this class of engine promises it", pending confirmation. The
`unknown` rows are where we genuinely do not know.

## No voice-cloning UI

Cloning appears only as **capability metadata**. There is deliberately no UI,
no "upload 10 seconds of your voice" flow, and no reference audio handling in
v1 — because shipping a cloning interface before anyone has heard one output
from this adapter would be building the front door before the house exists.

## Error mapping

| Situation | Result |
| --- | --- |
| no URL configured | `not_installed` |
| `/health` answers but is unhealthy | `unavailable` |
| `502` / `503` / `504` | `ProviderTimeout` — transient, worth a fallback |
| connection refused | `unavailable`, never an exception |

## Bringing it up for real (the missing step)

1. Run Fish Speech or CosyVoice in server mode on your GPU node.
2. `HVW_NEURAL_TTS_URL=http://<host>:<port> html-video providers`
3. Synthesize one sentence and **listen to it.**
4. Correct any row in the capability table that the probe contradicts, and move
   this file's status line out of `PENDING`.

Until step 4 happens, every report must keep saying this is unvalidated.
