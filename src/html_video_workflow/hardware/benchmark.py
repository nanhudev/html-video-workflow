"""BenchmarkService — measure the machine instead of guessing from model names.

Results are persisted to ``<home>/benchmarks.json`` and keyed by a hardware
fingerprint, so a hardware change invalidates them honestly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ..config.paths import benchmarks_path, cache_dir
from ..utils.logging import get_logger
from .profile import HardwareProfile, probe_hardware

log = get_logger("hardware.benchmark")

SCHEMA_VERSION = 1


def hardware_fingerprint(profile: HardwareProfile | None = None) -> str:
    profile = profile or probe_hardware()
    parts = [
        profile.cpu_model or "?",
        str(profile.cpu_logical_cores),
        str(profile.ram_total_mb),
        ";".join(f"{(g.model or g.vendor)}:{g.vram_mb}" for g in profile.gpus),
    ]
    return "|".join(parts)


def load_benchmarks() -> dict[str, Any]:
    path = benchmarks_path()
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "runs": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "runs": {}}


def save_benchmarks(data: dict[str, Any]) -> Path:
    path = benchmarks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record(key: str, value: dict[str, Any]) -> dict[str, Any]:
    data = load_benchmarks()
    data.setdefault("runs", {})
    data["runs"][key] = {**value, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    data["schema_version"] = SCHEMA_VERSION
    save_benchmarks(data)
    return data["runs"][key]


def get(key: str, fingerprint: str | None = None) -> dict[str, Any] | None:
    run = load_benchmarks().get("runs", {}).get(key)
    if not run:
        return None
    if fingerprint and run.get("fingerprint") and run["fingerprint"] != fingerprint:
        return None  # stale: hardware changed
    return run


# --------------------------------------------------------------- benchmarks
def benchmark_ffmpeg_encode(seconds: float = 3.0) -> dict[str, Any]:
    """Encode a synthetic clip and report fps. Requires ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"available": False, "reason": "ffmpeg not found"}
    out = cache_dir() / "benchmark_encode.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-v", "error", "-f", "lavfi",
        "-i", f"testsrc=size=1280x720:rate=30:duration={seconds}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", str(out),
    ]
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    elapsed = time.perf_counter() - start
    if result.returncode != 0 or not out.exists():
        return {"available": False, "reason": (result.stderr or "encode failed")[:300]}
    frames = int(seconds * 30)
    data = {
        "available": True,
        "encode_fps": round(frames / elapsed, 2) if elapsed > 0 else None,
        "wall_seconds": round(elapsed, 3),
        "frames": frames,
    }
    try:
        out.unlink()
    except OSError:
        pass
    return data


def benchmark_disk_write(mb: int = 128) -> dict[str, Any]:
    """Measure sequential write throughput in MB/s."""
    target = cache_dir() / "benchmark_disk.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    chunk = b"0" * (1 << 20)
    start = time.perf_counter()
    try:
        with target.open("wb") as handle:
            for _ in range(mb):
                handle.write(chunk)
            handle.flush()
    except OSError as exc:
        return {"available": False, "reason": str(exc)}
    elapsed = time.perf_counter() - start
    try:
        target.unlink()
    except OSError:
        pass
    return {
        "available": True,
        "write_mb_s": round(mb / elapsed, 1) if elapsed > 0 else None,
        "megabytes": mb,
    }


def benchmark_callable(name: str, func: Callable[[], float], samples: int = 3) -> dict[str, Any]:
    """Run a provider-supplied callable ``samples`` times, report median seconds."""
    durations: list[float] = []
    for index in range(samples):
        start = time.perf_counter()
        try:
            func()
        except Exception as exc:  # provider may legitimately fail
            return {"available": False, "reason": f"{type(exc).__name__}: {exc}"[:300]}
        durations.append(time.perf_counter() - start)
        if index + 1 < samples:
            time.sleep(0.05)
    durations.sort()
    return {
        "available": True,
        "median_seconds": round(durations[len(durations) // 2], 4),
        "samples": durations,
        "name": name,
    }


def run_core_benchmarks() -> dict[str, Any]:
    """Fast, always-safe benchmarks (no models required)."""
    fingerprint = hardware_fingerprint()
    results: dict[str, Any] = {"fingerprint": fingerprint, "schema_version": SCHEMA_VERSION}
    results["ffmpeg_encode"] = benchmark_ffmpeg_encode()
    results["disk_write"] = benchmark_disk_write()
    record(f"core::{fingerprint}", results)
    return results
