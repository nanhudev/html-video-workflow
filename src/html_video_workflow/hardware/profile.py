"""Real hardware probing.

Nothing here is hardcoded for a particular machine. Anything we cannot measure
stays ``None`` so the router can say "unknown" instead of inventing a fact.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config.paths import hardware_path
from ..utils.logging import get_logger

log = get_logger("hardware.profile")


@dataclass
class GpuInfo:
    vendor: str  # nvidia | amd | intel | apple | unknown
    model: str | None = None
    vram_mb: int | None = None
    driver_version: str | None = None
    source: str | None = None


@dataclass
class ToolInfo:
    name: str
    available: bool
    path: str | None = None
    version: str | None = None
    raw: str | None = None


@dataclass
class HardwareProfile:
    os: str
    os_version: str
    arch: str
    cpu_model: str | None
    cpu_physical_cores: int | None
    cpu_logical_cores: int | None
    ram_total_mb: int | None
    ram_free_mb: int | None
    gpus: list[GpuInfo] = field(default_factory=list)
    accelerators: dict[str, bool | None] = field(default_factory=dict)
    tooling: dict[str, ToolInfo] = field(default_factory=dict)
    disk_free_mb: int | None = None
    probed_at: str | None = None

    # ------------------------------------------------------------ helpers
    @property
    def primary_gpu(self) -> GpuInfo | None:
        return self.gpus[0] if self.gpus else None

    @property
    def vram_total_mb(self) -> int:
        return sum(g.vram_mb or 0 for g in self.gpus)

    @property
    def has_gpu(self) -> bool:
        return bool(self.gpus)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tooling"] = {k: asdict(v) for k, v in self.tooling.items()}
        # Derived values are part of the contract too: the Studio, the routing
        # planner and the CLI all reason about total VRAM, and a consumer that
        # only has the JSON should not have to re-derive it (or guess the key
        # name and read `undefined`).
        data["vram_total_mb"] = self.vram_total_mb
        data["has_gpu"] = self.has_gpu
        data["primary_gpu"] = self.primary_gpu.model if self.primary_gpu else None
        return data


# --------------------------------------------------------------------- run
def _run(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("probe command failed: %s (%s)", " ".join(cmd), exc)
        return None


def _first_line(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return None


# --------------------------------------------------------------------- CPU
def _windows_cpu_model() -> str | None:
    """Windows registry carries the marketing name, which is what humans read."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        name = str(value).strip()
        return name or None
    except OSError:
        return None


def _cpu_model() -> str | None:
    if os.name == "nt":
        registry_name = _windows_cpu_model()
        if registry_name:
            return registry_name
    model = platform.processor()
    if model and model not in {"", "AMD64", "x86_64", "Intel64 Family 6"}:
        return model
    if Path("/proc/cpuinfo").exists():
        try:
            for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            return None
    if platform.system() == "Darwin":
        result = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        return _first_line(result.stdout) if result else None
    return model or None


def _physical_cores() -> tuple[int | None, int | None]:
    logical = os.cpu_count()
    physical = None
    try:
        if hasattr(os, "process_cpu_count"):  # py3.13
            logical = os.process_cpu_count() or logical
    except Exception:  # pragma: no cover
        pass
    if Path("/proc/cpuinfo").exists():
        try:
            ids = {
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines()
                if line.lower().startswith("core id")
            }
            physical = len(ids) or None
        except OSError:
            physical = None
    elif platform.system() == "Darwin":
        result = _run(["sysctl", "-n", "hw.physicalcpu"])
        if result and result.stdout.strip().isdigit():
            physical = int(result.stdout.strip())
    elif os.name == "nt":
        physical = _windows_physical_cores()
    return physical, logical


def _windows_physical_cores() -> int | None:
    """Read core count from the CPU topology registry when available."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor"
        )
        count = 0
        index = 0
        while True:
            try:
                winreg.EnumKey(key, index)
            except OSError:
                break
            count += 1
            index += 1
        return count or None
    except OSError:
        return None


# --------------------------------------------------------------------- RAM
def _ram() -> tuple[int | None, int | None]:
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return (
                    stat.ullTotalPhys // (1024 * 1024),
                    stat.ullAvailPhys // (1024 * 1024),
                )
        except Exception:  # pragma: no cover
            pass
    if Path("/proc/meminfo").exists():
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(errors="replace").splitlines():
                match = re.match(r"(\w+):\s+(\d+)", line)
                if match:
                    values[match.group(1)] = int(match.group(2)) // 1024
            return values.get("MemTotal"), values.get("MemAvailable")
        except OSError:
            return None, None
    if platform.system() == "Darwin":
        total = _run(["sysctl", "-n", "hw.memsize"])
        if total and total.stdout.strip().isdigit():
            return int(total.stdout.strip()) // (1024 * 1024), None
    return None, None


# --------------------------------------------------------------------- GPU
def _gpu_from_nvidia_smi() -> list[GpuInfo]:
    if not shutil.which("nvidia-smi"):
        return []
    result = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    gpus: list[GpuInfo] = []
    if not result or result.returncode != 0:
        return gpus
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        vram = None
        if len(parts) > 1 and parts[1].isdigit():
            vram = int(parts[1])
        gpus.append(
            GpuInfo(
                vendor="nvidia",
                model=parts[0],
                vram_mb=vram,
                driver_version=parts[2] if len(parts) > 2 else None,
                source="nvidia-smi",
            )
        )
    return gpus


def _gpu_from_powershell() -> list[GpuInfo]:
    """Windows: query Win32_VideoController through CIM."""
    if os.name != "nt":
        return []
    command = (
        "Get-CimInstance Win32_VideoController | "
        "ForEach-Object { $_.Name + '|' + $_.DriverVersion + '|' + $_.AdapterRAM }"
    )
    result = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=40
    )
    if not result or result.returncode != 0 or not result.stdout.strip():
        return []
    gpus: list[GpuInfo] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, driver, ram = (line.split("|") + ["", ""])[:3]
        name = name.strip()
        vram = None
        try:
            raw = int(ram.strip())
            # AdapterRAM is often reported as a 32-bit wrapped value.
            if raw > 0:
                vram = raw // (1024 * 1024)
                if vram > 128 * 1024:  # implausible → wrapped/unreliable
                    vram = None
        except ValueError:
            vram = None
        gpus.append(
            GpuInfo(
                vendor=_vendor_of(name),
                model=name or None,
                vram_mb=vram,
                driver_version=driver.strip() or None,
                source="win32_videocontroller",
            )
        )
    return gpus


def _gpu_from_lspci() -> list[GpuInfo]:
    if platform.system() != "Linux" or not shutil.which("lspci"):
        return []
    result = _run(["lspci"])
    if not result:
        return []
    gpus: list[GpuInfo] = []
    for line in result.stdout.splitlines():
        if " vga " not in line.lower() and " 3d " not in line.lower():
            continue
        label = line.split(":", 2)[-1].strip()
        gpus.append(GpuInfo(vendor=_vendor_of(label), model=label, source="lspci"))
    return gpus


def _gpu_from_system_profiler() -> list[GpuInfo]:
    if platform.system() != "Darwin":
        return []
    result = _run(["system_profiler", "SPDisplaysDataType"], timeout=40)
    if not result:
        return []
    gpus: list[GpuInfo] = []
    current: GpuInfo | None = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and ("Chipset Model" in stripped or "Chip" in stripped):
            current = GpuInfo(vendor="apple", model=None, source="system_profiler")
        elif current is not None:
            if stripped.startswith("Chipset Model:"):
                current.model = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("VRAM"):
                match = re.search(r"(\d+)\s*(MB|GB)", stripped)
                if match:
                    amount = int(match.group(1))
                    current.vram_mb = amount * 1024 if match.group(2) == "GB" else amount
                    gpus.append(current)
                    current = None
    if current and current.model:
        gpus.append(current)
    return gpus


def _vendor_of(name: str | None) -> str:
    if not name:
        return "unknown"
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "rtx" in lowered or "gtx" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered or "rx " in lowered:
        return "amd"
    if "intel" in lowered or "arc" in lowered or "iris" in lowered:
        return "intel"
    if "apple" in lowered or "m1" in lowered or "m2" in lowered or "m3" in lowered:
        return "apple"
    if "microsoft basic" in lowered:
        return "software"
    return "unknown"


def _detect_gpus() -> list[GpuInfo]:
    gpus = _gpu_from_nvidia_smi()
    gpus += _gpu_from_powershell()
    gpus += _gpu_from_lspci()
    gpus += _gpu_from_system_profiler()
    return _dedupe_gpus(gpus)


def _dedupe_gpus(gpus: list[GpuInfo]) -> list[GpuInfo]:
    """nvidia-smi wins over generic listings for the same device."""
    seen: dict[str, GpuInfo] = {}
    for gpu in gpus:
        key = (gpu.model or gpu.vendor).lower()
        existing = seen.get(key)
        if existing is None or (existing.vram_mb is None and gpu.vram_mb is not None):
            seen[key] = gpu
    ordered = sorted(seen.values(), key=lambda g: (g.vram_mb or 0), reverse=True)
    return ordered


# ---------------------------------------------------------- accelerators
def _detect_accelerators(gpus: list[GpuInfo]) -> dict[str, bool | None]:
    nvidia = any(g.vendor == "nvidia" for g in gpus)
    amd = any(g.vendor == "amd" for g in gpus)
    system = platform.system()
    rocm = None
    if amd or system == "Linux":
        result = _run(["rocminfo", "--support"]) if shutil.which("rocminfo") else None
        rocm = bool(result and result.returncode == 0) if shutil.which("rocminfo") else None
    vulkan = None
    if shutil.which("vulkaninfo"):
        result = _run(["vulkaninfo", "--summary"], timeout=30)
        vulkan = bool(result and result.returncode == 0)
    return {
        "cuda": bool(shutil.which("nvidia-smi")) if nvidia else False,
        "rocm_hip": rocm,
        "vulkan": vulkan,
        "directml": True if system == "Windows" else None,
        "metal": True
        if system == "Darwin"
        else (None if system != "Windows" and system != "Linux" else False),
        "coreml": True if system == "Darwin" else None,
    }


# ------------------------------------------------------------------- tools
def _tool(name: str, version_args: list[str] | None = None) -> ToolInfo:
    path = shutil.which(name)
    if not path:
        return ToolInfo(name=name, available=False)
    version = None
    raw = None
    result = _run([path, *(version_args or ["-version"])], timeout=20)
    if result:
        raw = (result.stdout or result.stderr or "").strip()
        version = _first_line(raw)
        if version and len(version) > 160:
            version = version[:160]
    return ToolInfo(name=name, available=True, path=path, version=version, raw=raw)


_BROWSER_CANDIDATES = (
    "msedge",
    "chrome",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)

_BROWSER_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def resolve_browser() -> ToolInfo:
    """Find a Chromium-compatible browser: Edge → Chrome → Chromium."""
    for name in _BROWSER_CANDIDATES:
        path = shutil.which(name)
        if path:
            info = _tool(name, ["--version"])
            if info.available:
                return ToolInfo(
                    name=name,
                    available=True,
                    path=path,
                    version=info.version,
                    raw=info.raw,
                )
    for candidate in _BROWSER_PATHS:
        if Path(candidate).exists():
            return ToolInfo(name=Path(candidate).stem, available=True, path=candidate)
    return ToolInfo(name="chromium", available=False)


def _detect_tooling() -> dict[str, ToolInfo]:
    tooling = {
        "ffmpeg": _tool("ffmpeg", ["-version"]),
        "ffprobe": _tool("ffprobe", ["-version"]),
        "browser": resolve_browser(),
        "node": _tool("node", ["--version"]),
        "npm": _tool("npm", ["--version"]),
    }
    python_exe = shutil.which("python") or shutil.which("python3")
    tooling["python"] = ToolInfo(
        name="python",
        available=bool(python_exe),
        path=python_exe,
        version=platform.python_version(),
    )
    return tooling


# ------------------------------------------------------------------- entry
def probe_hardware(use_cache: bool = True, max_cache_age_sec: int = 3600) -> HardwareProfile:
    """Probe the machine. Cache is best-effort; probing is cheap and honest."""
    if use_cache:
        cached = _load_cached(max_cache_age_sec)
        if cached:
            return cached
    physical, logical = _physical_cores()
    ram_total, ram_free = _ram()
    gpus = _detect_gpus()
    try:
        disk_free = shutil.disk_usage(str(Path.home())).free // (1024 * 1024)
    except OSError:
        disk_free = None
    profile = HardwareProfile(
        os=platform.system(),
        os_version=platform.version(),
        arch=platform.machine(),
        cpu_model=_cpu_model(),
        cpu_physical_cores=physical,
        cpu_logical_cores=logical,
        ram_total_mb=ram_total,
        ram_free_mb=ram_free,
        gpus=gpus,
        accelerators=_detect_accelerators(gpus),
        tooling=_detect_tooling(),
        disk_free_mb=disk_free,
        probed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    _save_cached(profile)
    return profile


def _save_cached(profile: HardwareProfile) -> None:
    try:
        path = hardware_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover
        log.warning("unable to persist hardware profile: %s", exc)


def _load_cached(max_age_sec: int) -> HardwareProfile | None:
    path = hardware_path()
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > max_age_sec:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    gpus = [GpuInfo(**g) for g in data.get("gpus", [])]
    tooling = {k: ToolInfo(**v) for k, v in data.get("tooling", {}).items()}
    return HardwareProfile(
        os=data.get("os", platform.system()),
        os_version=data.get("os_version", ""),
        arch=data.get("arch", platform.machine()),
        cpu_model=data.get("cpu_model"),
        cpu_physical_cores=data.get("cpu_physical_cores"),
        cpu_logical_cores=data.get("cpu_logical_cores"),
        ram_total_mb=data.get("ram_total_mb"),
        ram_free_mb=data.get("ram_free_mb"),
        gpus=gpus,
        accelerators=data.get("accelerators", {}),
        tooling=tooling,
        disk_free_mb=data.get("disk_free_mb"),
        probed_at=data.get("probed_at"),
    )
