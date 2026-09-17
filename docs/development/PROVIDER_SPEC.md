# PROVIDER_SPEC

A Provider is the only place where an external capability (model, engine,
service, binary) is allowed to be known by name. Nothing above the provider
layer may contain `if local_model:` / `if gpu == "rtx4060":` logic.

---

## 1. Provider contract

```python
class Provider(ABC):
    spec: ProviderSpec                     # static declaration

    def probe(self) -> ProbeResult: ...    # REAL check, never optimistic
    def capabilities(self) -> Capability: ...
    def execute(self, request, ctx) -> ProviderResult: ...   # one narrow job
```

Rules:

1. **Honesty first.** `probe()` must actually touch the binary / port / file /
   API it depends on. `not_installed`, `unavailable`, `missing_credentials` are
   legitimate results. Returning "Ready" without proof is a bug.
2. **One capability per provider.** No provider does TTS *and* rendering.
3. **No heavy imports at module import time.** `torch`, `diffusers`,
   `onnxruntime` etc. may only be imported inside `execute()`. Core must stay
   installable without them.
4. **Process isolation preferred.** HTTP service or subprocess sidecar over
   in-process import, so two providers can never fight over dependency versions.
5. **Deterministic inputs produce deterministic outputs** where the backend
   allows it (seed/version recorded in the artifact).
6. **Errors are typed**, human readable, and carry a fallback hint.

## 2. ProviderSpec (declaration)

```jsonc
{
  "id": "sapi",
  "type": "tts",
  "name": "Windows SAPI",
  "vendor": "Microsoft",
  "local": true,
  "implementation": "subprocess",        // inprocess | subprocess | http | api
  "languages": ["zh-CN", "en-US"],       // BCP-47, empty = unknown/any
  "quality_score": 5.0,                  // 0..10, subjective but documented
  "speed_score": 9.0,
  "naturalness_score": 4.5,
  "streaming": false,
  "gpu": false,
  "cpu": true,
  "estimated_vram_mb": 0,
  "estimated_ram_mb": 64,
  "startup_cost": "low",                 // low | medium | high
  "requires": { "os": ["windows"], "binary": [] },
  "install": { "state": "builtin", "docs": "" },
  "license": { "code": "OS", "model": null, "commercial": "unclear",
               "attribution": false },
  "voice_type": "built_in",              // built_in | licensed | user_owned | clone
  "tags": ["fallback", "offline"]
}
```

## 3. Capability (measured / probed)

```jsonc
{
  "id": "sapi",
  "type": "tts",
  "available": true,
  "local": true,
  "languages": ["zh-CN", "en-US"],
  "voices": [ { "id": "Microsoft Huihui Desktop", "language": "zh-CN", "gender": "female" } ],
  "streaming": false,
  "gpu": false,
  "cpu": true,
  "estimated_vram_mb": 0,
  "quality_score": 5.0,
  "speed_score": 9.0,
  "naturalness_score": 4.5,
  "startup_cost": "low",
  "details": { ... provider-specific ... }
}
```

`capabilities()` may only downgrade scores relative to `spec` (e.g. fewer
voices detected). It may never invent capability that `probe()` did not verify.

## 4. Provider types (Foundation status)

| Type | Implemented in Foundation | Planned |
|---|---|---|
| `llm` | `openai_compatible`, `mock_llm` | Ollama, llama.cpp server, LM Studio, vLLM (all via openai-compatible) |
| `tts` | `sapi`, `moss`, `mock_tts` | AivisSpeech, VOICEVOX-compatible, Fish Speech, CosyVoice, GPT-SoVITS, Piper, API TTS |
| `asr` | — (interface only) | whisper.cpp, faster-whisper |
| `renderer` | `legacy_html`, `mock_renderer` | Remotion, Motion Canvas, WebMotion-style linted HTML |
| `avatar` | — (interface only) | MuseTalk, LivePortrait, LiveTalking |
| `image` | — (interface only) | local SD/Flux sidecar, API image |
| `video` | — (interface only) | generative video APIs |
| `music` | — (interface only) | local library + API |
| `asset` | `local_asset` | stock, screenshot, screen recording |
| `subtitle` | `srt` (writer) | ASS, WebVTT, word-level timing |
| `storage` | `local_fs` | S3-compatible |
| `agent` | — (interface only) | external agent loops |

## 5. Registration

```python
from html_video_workflow.providers import register

@register
class MyTTS(TTSProvider):
    spec = ProviderSpec(id="mytts", type="tts", ...)
```

Discovery order: built-in modules under `providers/<type>/`, then entry points
group `html_video_workflow.providers`, then `~/.html-video-workflow/providers/`.

## 6. ProbeResult

```jsonc
{
  "state": "ready",          // ready | not_installed | unavailable | missing_credentials | error
  "reason": "sapi_tts.ps1 found, 3 zh-CN voices detected",
  "checked_at": "2026-09-15T00:00:00Z",
  "evidence": { "voices": 3, "binary": "C:\\...\\System.Speech" }
}
```

States are never coerced to `ready`. The Studio renders `not_installed` with an
install hint, not a green dot.

## 7. Benchmarks

Optional `benchmark()` returns measurable numbers per type:

* `llm`: `tokens_per_second`, `time_to_first_token_ms`
* `tts`: `rtf` (realtime factor), `seconds_per_100_chars`
* `renderer`: `frames_per_second`, `ms_per_scene`
* `ffmpeg`: `encode_fps`

Results are stored in `~/.html-video-workflow/benchmarks.json` and used by the
router. Missing benchmark ≠ failure: the router falls back to declared scores.

## 8. Licensing record

Every provider carries a `license` block **before** it is merged:

```
code license · model license · commercial limitation · attribution · redistribution
```

Open-source *code* never implies commercial *weights*. Fish Speech, CosyVoice,
GPT-SoVITS and voice models must be reviewed individually.

## 9. Voice safety

`voice_type: clone` requires an explicit user confirmation in the UI and a
`user_owned` reference clip path. The product never defaults to cloning a public
figure's voice.
