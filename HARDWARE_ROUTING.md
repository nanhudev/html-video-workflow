# Hardware Profiling & Auto Routing

Goal: the user never has to know what `Fish Speech`, `llama.cpp`, `Vulkan` or
`RTF` mean. They pick `Auto / Fast / Balanced / High Quality / Max Quality` and
the runtime picks — **with reasons**.

---

## 1. HardwareProfile

Probed live. Nothing is hardcoded, and an unknown field is `null`, never guessed.

```
os · os_version · arch
cpu_model · cpu_physical_cores · cpu_logical_cores · cpu_freq_mhz
ram_total_mb · ram_free_mb
gpus[]: vendor · model · vram_mb · driver_version
accelerators: cuda · rocm_hip · vulkan · directml · metal · coreml
tooling: ffmpeg · ffprobe · chromium (browser path) · python · node
disk_free_mb
```

Vendors handled: `nvidia | amd | intel | apple | unknown | cpu_only`.

Probe sources:

| Field | Windows | Linux | macOS |
|---|---|---|---|
| CPU/RAM | `platform`, `os`, `/proc/meminfo`, CIM | `/proc/cpuinfo`, `/proc/meminfo` | `sysctl`, `system_profiler` |
| GPU | CIM `Win32_VideoController`, `nvidia-smi` | `lspci`, `rocm-smi`, `nvidia-smi` | `system_profiler SPDisplaysDataType` |
| VRAM | CIM `AdapterRAM` + `nvidia-smi` | `nvidia-smi`, sysfs | `system_profiler` |
| CUDA | `nvidia-smi` present + `CUDA_PATH` | `nvidia-smi`, `libcuda.so` | — |
| ROCm/HIP | `rocminfo` | `rocminfo`, `/opt/rocm` | — |
| Vulkan | `vulkaninfo` | `vulkaninfo` | `vulkaninfo`, MoltenVK |
| DirectML | DirectX dxgi via CIM | — | — |
| Metal | — | — | `system_profiler` + OS ≥ 12 |

The result is cached for the process and persisted to
`~/.html-video-workflow/hardware.json` with a timestamp. `html-video doctor`
re-probes and prints it.

## 2. BenchmarkService

First run (and on demand via `html-video benchmark`) measures:

* `llm.tokens_per_second`, `llm.ttft_ms` — against the configured LLM endpoint
* `tts.rtf` — synth 3 short samples, `rtf = audio_seconds / wall_seconds`
* `renderer.ms_per_scene` — render N probe scenes
* `ffmpeg.encode_fps` — encode a 5s 720p clip
* `disk.write_mb_s`
* `gpu.vram_free_mb` (when measurable)

Stored at `~/.html-video-workflow/benchmarks.json`, keyed by
`provider_id + provider_version + hardware fingerprint`. A missing benchmark is
never treated as a good benchmark: the router falls back to declared scores and
says so in `reason[]`.

## 3. Presets

| Preset | Bias |
|---|---|
| `Fast` | startup cost low, CPU-only TTS, cached assets, fewer generative visuals, lower resolution OK |
| `Balanced` | weighted `quality 0.4 / speed 0.3 / memory 0.2 / startup 0.1` |
| `High Quality` | allows slower TTS, richer motion, more assets, 1080p+ |
| `Max Quality` | only offered when VRAM/RAM headroom is proven; enables local generative + avatar |
| `Auto` | reads the project (type, duration, language, density) then picks a preset |

## 4. Scoring

```
score = w_quality * quality_score
      + w_speed   * speed_score
      + w_natural * naturalness_score
      - startup_penalty
      - vram_penalty        # required_vram > free_vram → provider is excluded
      - license_penalty     # commercial-unclear lowered for commercial projects
      + language_fit_bonus  # provider speaks project.language
      + benchmark_bonus     # measured RTF / tok-s beats declared estimate
```

Hard filters applied *before* scoring:

1. provider `available == true` (from a real `probe()`),
2. language supported,
3. estimated VRAM ≤ free VRAM (with 15% headroom),
4. user overrides (`locked` providers) win unconditionally.

## 5. Explainability

Every selection returns reasons:

```json
{
  "stage": "tts",
  "selected": "sapi",
  "preset": "fast",
  "candidates": [
    { "id": "sapi",  "score": 7.4, "chosen": true,
      "reason": ["supports zh-CN", "available locally", "startup low", "no VRAM required"] },
    { "id": "moss",  "score": 6.1, "chosen": false,
      "reason": ["binary not found: moss-tts-nano", "state=not_installed"] }
  ],
  "fallbacks": ["mock_tts"]
}
```

Rejected candidates keep their rejection reason — the UI shows *why not*, not
just *what*.

## 6. Fallback chains

```yaml
tts:      [fish_speech, cosyvoice, moss, sapi, mock_tts]
renderer: [advanced_html, legacy_html, mock_renderer]
llm:      [openai_compatible, mock_llm]
```

A fallback is only used after a typed provider failure, and the substitution is
recorded in `runtime/job.json` + `runtime/quality.json`. Silent downgrade is
forbidden.

## 7. No fake recommendations

If no provider can satisfy a stage, the runtime reports
`UnsupportedCapability` with the blocking reason (e.g. "no zh-CN TTS available;
install Fish Speech or enable an API TTS"). It never substitutes silence for
audio and calls the job successful.
