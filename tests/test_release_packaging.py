"""The release zip must contain a working ffmpeg, not a package manager's proxy.

This is the one failure a release cannot recover from. A proxy executable runs
on the build machine — the absolute path baked into its shim descriptor exists
there — so the release workflow's own smoke test passes, and the zip is
published. Every user then gets a bundle that dies on the first render, with an
error that looks like a bug in the app rather than a bad download.

So the packaging is tested for the property that matters: what lands in ``bin/``
is the real tool, and a build that would ship a proxy fails loudly instead.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]

# `scripts/` is not an importable package, and pack_release is a build entry
# point rather than library code, so load it by path.
_REAL = 3 * 1024 * 1024      # comfortably above the 1 MB proxy threshold
_PROXY = 64 * 1024           # a shim is tens of KB


@pytest.fixture(scope="module")
def pack_release() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pack_release_under_test", ROOT / "scripts" / "pack_release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


def _real_pair(directory: Path) -> None:
    _write(directory / "ffmpeg.exe", _REAL)
    _write(directory / "ffprobe.exe", _REAL)


def test_a_real_binary_is_used_as_is(pack_release, tmp_path):
    binary = _write(tmp_path / "ffmpeg.exe", _REAL)

    assert pack_release.resolve_tool(binary).resolve() == binary.resolve()


def test_a_chocolatey_shim_is_followed_to_the_real_binary(pack_release, tmp_path):
    """`ffmpeg.exe` beside `ffmpeg.exe.shim`, the descriptor naming the target."""
    shim_dir = tmp_path / "chocolatey" / "bin"
    real = _write(tmp_path / "lib" / "ffmpeg" / "bin" / "ffmpeg.exe", _REAL)
    shim = _write(shim_dir / "ffmpeg.exe", _PROXY)
    (shim_dir / "ffmpeg.exe.shim").write_text(
        '<?xml version="1.0"?>\n<config>\n'
        f"  <command>{real}</command>\n</config>\n",
        encoding="utf-8")

    assert pack_release.resolve_tool(shim).resolve() == real.resolve()


def test_a_scoop_style_shim_is_followed_too(pack_release, tmp_path):
    """Scoop names the descriptor after the command, without the extension."""
    shim_dir = tmp_path / "scoop" / "shims"
    real = _write(tmp_path / "apps" / "ffmpeg" / "current" / "bin" / "ffmpeg.exe", _REAL)
    shim = _write(shim_dir / "ffmpeg.exe", _PROXY)
    (shim_dir / "ffmpeg.shim").write_text(
        f'path = "{real}"\nargs = \n', encoding="utf-8")

    assert pack_release.resolve_tool(shim).resolve() == real.resolve()


def test_win_get_style_reparse_point_is_followed(pack_release, tmp_path):
    """WinGet's `Links` directory uses a real symbolic link, not a descriptor."""
    real = _write(tmp_path / "packages" / "Gyan.FFmpeg" / "bin" / "ffmpeg.exe", _REAL)
    link = tmp_path / "Links" / "ffmpeg.exe"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("this machine will not create symbolic links unprivileged")

    assert pack_release.resolve_tool(link).resolve() == real.resolve()


def test_a_forward_slash_path_is_understood(pack_release, tmp_path):
    """CI builds on Linux, where a descriptor's path carries no drive letter.

    A regex that insists on ``C:\\`` would pass on the developer's Windows box
    and fail the release build on the runner — the mirror image of the bug this
    whole module exists to prevent.
    """
    real = _write(tmp_path / "usr" / "local" / "bin" / "ffmpeg.exe", _REAL)
    shim_dir = tmp_path / "shims"
    shim = _write(shim_dir / "ffmpeg.exe", _PROXY)
    (shim_dir / "ffmpeg.shim").write_text(
        f'path = "{real.as_posix()}"\n', encoding="utf-8")

    assert pack_release.resolve_tool(shim).resolve() == real.resolve()


def test_an_unquoted_path_is_understood(pack_release, tmp_path):
    """Not every manager quotes the path it records."""
    real = _write(tmp_path / "opt" / "ffmpeg" / "bin" / "ffmpeg.exe", _REAL)
    shim_dir = tmp_path / "shims"
    shim = _write(shim_dir / "ffmpeg.exe", _PROXY)
    (shim_dir / "ffmpeg.exe.shim").write_text(
        f"command={real}\n", encoding="utf-8")

    assert pack_release.resolve_tool(shim).resolve() == real.resolve()


def test_a_proxy_without_a_usable_descriptor_is_refused(pack_release, tmp_path):
    """Refused, not passed through: passing it through is what ships a broken zip."""
    shim = _write(tmp_path / "bin" / "ffmpeg.exe", _PROXY)

    assert pack_release.resolve_tool(shim) is None


def test_a_descriptor_pointing_nowhere_is_refused(pack_release, tmp_path):
    """A stale descriptor must not be trusted into a `None`-path crash."""
    shim_dir = tmp_path / "bin"
    shim = _write(shim_dir / "ffmpeg.exe", _PROXY)
    (shim_dir / "ffmpeg.exe.shim").write_text(
        "<command>C:\\gone\\ffmpeg.exe</command>", encoding="utf-8")

    assert pack_release.resolve_tool(shim) is None


def test_a_missing_binary_resolves_to_nothing(pack_release, tmp_path):
    assert pack_release.resolve_tool(tmp_path / "ffmpeg.exe") is None


def test_bundling_copies_the_real_pair_into_bin(pack_release, tmp_path):
    tools = tmp_path / "tools"
    _real_pair(tools)
    app = tmp_path / "app"
    app.mkdir()

    copied = pack_release.bundle_tools(app, str(tools), allow_missing=False)

    assert sorted(copied) == ["ffmpeg.exe", "ffprobe.exe"]
    assert (app / "bin" / "ffmpeg.exe").stat().st_size == _REAL
    assert (app / "bin" / "ffprobe.exe").stat().st_size == _REAL


def test_a_tools_directory_holding_only_a_proxy_fails_the_build(pack_release, tmp_path):
    """The realistic case: `--ffmpeg-bin` points at the manager's shim folder.

    Nothing resolves, so nothing is bundled, and the missing-tools rule stops the
    build. Either way it stops here rather than at the user's first render.
    """
    tools = tmp_path / "tools"
    _write(tools / "ffmpeg.exe", _PROXY)
    _write(tools / "ffprobe.exe", _PROXY)
    app = tmp_path / "app"
    app.mkdir()

    with pytest.raises(SystemExit):
        pack_release.bundle_tools(app, str(tools), allow_missing=False)


def test_a_proxy_that_slips_past_resolution_is_caught_before_the_copy(
        pack_release, tmp_path, monkeypatch):
    """Belt and braces: the size of what lands in `bin/` is checked, not assumed.

    `resolve_tool` is the only thing standing between a shim and the zip, so if
    it is ever loosened, this is the assertion that notices.
    """
    tools = tmp_path / "tools"
    proxy = _write(tools / "ffmpeg.exe", _PROXY)
    _write(tools / "ffprobe.exe", _REAL)
    monkeypatch.setattr(pack_release, "resolve_tool", lambda candidate: proxy
                        if candidate.exists() else None)
    app = tmp_path / "app"
    app.mkdir()

    with pytest.raises(SystemExit) as excinfo:
        pack_release.bundle_tools(app, str(tools), allow_missing=False)

    assert "代理程序" in str(excinfo.value)


def test_missing_tools_fail_the_build_by_default(pack_release, tmp_path):
    """"Nothing else to install" is the promise; a tool-less zip breaks it."""
    empty = tmp_path / "empty"
    empty.mkdir()
    app = tmp_path / "app"
    app.mkdir()

    with pytest.raises(SystemExit):
        pack_release.bundle_tools(app, str(empty), allow_missing=False)


def test_missing_tools_are_tolerable_when_explicitly_allowed(pack_release, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    app = tmp_path / "app"
    app.mkdir()

    assert pack_release.bundle_tools(app, str(empty), allow_missing=True) == []


def test_the_zip_carries_the_readme_and_the_bin_folder(pack_release, tmp_path):
    """One directory level inside the zip, so unzipping does not spray files."""
    import zipfile

    app = tmp_path / "html-video"
    app.mkdir()
    (app / "html-video.exe").write_bytes(b"\0" * 1024)
    _real_pair(app / "bin")
    out = tmp_path / "out"
    out.mkdir()

    archive = pack_release.make_zip(app, out, "1.2.3")

    assert archive.name == "html-video-windows-x64-1.2.3.zip"
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "html-video/html-video.exe" in names
    assert "html-video/bin/ffmpeg.exe" in names
    assert "html-video/使用说明.txt" in names


def test_the_documented_commands_are_real_flags(pack_release):
    """The module docstring is what a maintainer copies; keep it executable."""
    parser = pack_release.argparse.ArgumentParser()
    for flag in ("--skip-exe", "--skip-frontend", "--ffmpeg-bin", "--allow-no-tools"):
        parser.add_argument(flag, nargs="?")
        parser.parse_args([flag])
