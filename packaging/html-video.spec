# PyInstaller spec for the portable Windows build.
#
# The product promise is "download it and it works", so the bundle has to carry
# everything the pipeline needs: the built frontend, the template manifests, the
# untouched legacy script and helper, the JSON schemas — and ffmpeg, which
# `scripts/pack_release.py` drops into `bin/` next to the executable afterwards
# because it is 80 MB and has no business inside the archive.
#
# Build it with:  python scripts/pack_release.py
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
SRC = ROOT / "src"

datas = [
    # The built Studio. `studio_candidates()` looks for it inside the package.
    (str(SRC / "html_video_workflow" / "studio_dist"), "html_video_workflow/studio_dist"),
    # Read-only assets resolved through `resource_dir()`.
    (str(ROOT / "scripts" / "sapi_tts.ps1"), "scripts"),
    (str(ROOT / "scripts" / "workflow.py"), "scripts"),
    (str(ROOT / "schemas"), "schemas"),
]

binaries = []
hiddenimports = [
    # Imported lazily so the CLI stays usable without the API extra; a lazy
    # import is invisible to PyInstaller's static walk.
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# The template manifests and the rest of the package's data files travel with
# the package rather than being listed by hand: a new JSON manifest picked up by
# the registry must not require editing this file to be shipped.
for package in ("html_video_workflow", "fastapi", "starlette", "pydantic", "anyio"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception as exc:  # noqa: BLE001 - a missing optional dependency
        print(f"[spec] collect_all({package}) failed: {exc}")
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="html-video",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="html-video",
)
