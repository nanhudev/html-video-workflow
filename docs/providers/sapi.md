# SAPI TTS (`sapi`)

Windows system speech via the existing PowerShell helper.

**This is the only provider that is guaranteed to exist on a Windows machine.
It is the last link in every fallback chain.**

| | |
| --- | --- |
| Implementation | `subprocess` → `scripts/sapi_tts.ps1` |
| Local | yes |
| Quality tier | `robotic` |
| GPU | `no` |
| Model download | none |

## Why it matters despite the tier

SAPI's tier is `robotic` because it genuinely is. But a video with robotic
narration is worth more than a video whose pipeline threw an exception on
scene 3. SAPI is what makes the renderer honest about "this machine can always
produce *something*".

## Capabilities

Anything below marked `no` has been **probed and found absent**, not assumed.

| Feature | Support |
| --- | --- |
| emotion | `no` |
| style | `no` |
| voice clone | `no` |
| speed / rate | `yes` |
| pitch | `no` |
| emphasis | `no` |
| streaming | `no` |
| SSML | `unknown` |

`speed` maps to the SAPI rate control; `pitch` is reported `no` because the
helper does not expose it, and claiming otherwise would make the router route a
request it cannot fulfil.

## Configuration

No required configuration. Voice selection comes from the system's installed
voices, enumerated by `list_voices()`; on a machine with no voices the list is
empty rather than invented.

## Behaviour

- **Probe** lists installed voices. Zero voices ⇒ `UNAVAILABLE`, never `READY`.
- **`synthesize_rich`** reports `unsupported_fields` for every requested feature
  it cannot map, so a downgraded request is visible in the result instead of
  being silently dropped.

## Verification status

Validated on Windows with a real voice list and real synthesis.
**Not simulated.**
