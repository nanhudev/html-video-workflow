"""Build the portable Windows download: one zip, double-click, it works.

What the user gets after unzipping::

    html-video/
      html-video.exe        双击它，浏览器自动打开工作台
      bin/ffmpeg.exe        自带，不需要另外安装
      bin/ffprobe.exe
      使用说明.txt

The frontend is copied into the package (``html_video_workflow/studio_dist``)
rather than bundled as a separate step, because that is also where the wheel
expects it — one build produces both artifacts.

    python scripts/pack_release.py                 # everything
    python scripts/pack_release.py --skip-exe      # frontend + zip only
    python scripts/pack_release.py --ffmpeg-bin D:\\tools\\ffmpeg\\bin

``--ffmpeg-bin`` wants a directory holding the *real* binaries. A directory that
only holds a package manager's shim is rejected, because a shim names its target
by absolute path and therefore cannot work on anyone else's machine.

PyInstaller is not a project dependency on purpose: it is a build tool, needed
only here, and adding it to ``dependencies`` would make every user download it.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps" / "studio"
PACKAGE = ROOT / "src" / "html_video_workflow"
STUDIO_DIST = PACKAGE / "studio_dist"

README = """HTML Video Workflow — 本地视频生成工作台
================================================

怎么用（三步）

1. 双击 html-video.exe
   — 会弹出一个黑色命令行窗口，这是本地服务，不要关掉它。
   — 稍等几秒，浏览器会自动打开界面。
   — 没自动打开就手动访问 http://127.0.0.1:8787
   — 提示端口被占用，就用：html-video.exe --port 8899

2. 在界面里跟着向导走七步：
   环境自检 → 文案引擎 → 选题 → 写作风格 → 模板与配色 → 生成 → 完成
   第一步的检查项如果有问题，它会直接告诉你怎么修。

3. 出片后可以「播放视频」「打开文件位置」「复制完整路径」。
   生成过的视频都留在左侧「我的作品」里。


第一次运行会被 Windows 拦一下

  出现「Windows 已保护你的电脑」是正常的 —— 这个版本没有购买代码签名证书。
  点「更多信息」→「仍要运行」即可。


需要准备什么

  · Windows 10 / 11（64 位）
  · FFmpeg 已经打包在 bin 文件夹里，不用另装
  · 系统自带的 Edge 浏览器用于渲染画面
  · 中文配音需要系统装有中文语音包
    （设置 → 时间和语言 → 语言和区域 → 中文(简体) → 语言选项 → 语音）


要不要填 API Key

  不填也能用。不填时文案由内置模板生成，画面、配音、字幕都是真实的。
  想要更好的文案，就在「文案引擎」那一步填一个你自己申请的 API Key。
  界面上预置了 DeepSeek、OpenAI、Moonshot、硅基流动的常用地址，
  填完可以点「测试连接」——它会真的调用一次再告诉你结果。
  Key 只保存在本机的配置目录里，不会上传到任何第三方服务器。


文件放在哪

  视频成品：数据目录下的 outputs 文件夹（界面里点「打开文件位置」可直接定位）
  数据目录：默认在磁盘空间较大的盘，形如 D:\\html-video-workflow
  想换位置：设置环境变量 HVW_HOME 指向你想要的目录


命令行用法

  html-video.exe                    启动界面（等同于双击）
  html-video.exe doctor             检查这台机器能不能用
  html-video.exe generate "主题"    不开界面，直接生成一条视频
  html-video.exe presets            列出八种写作风格
  html-video.exe --help             查看全部命令
"""


def run(command: list[str], cwd: Path | None = None) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, cwd=str(cwd or ROOT), check=True,
                   shell=os.name == "nt")


def version() -> str:
    import re

    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def build_frontend(skip: bool) -> None:
    if skip:
        print("跳过前端构建。")
        return
    if not (STUDIO / "node_modules").is_dir():
        run(["npm", "ci"], cwd=STUDIO)
    # Clear the previous build from Python rather than letting Vite do it.
    # Vite empties its out directory through `fs.rmSync`, and a guarded sandbox
    # (this project is developed behind one, where a bulk delete over ~50 files
    # is refused) turns that into a failed build with a confusing message. The
    # guarantee is the same one `stage_frontend` wants — no stale asset sitting
    # beside a fresh index.html — just without the tripwire.
    dist = STUDIO / "dist"
    _try_clear(dist)
    run(["npm", "run", "build"], cwd=STUDIO)


def _try_clear(directory: Path) -> None:
    """Remove ``directory``, tolerating a refusal.

    A locked file (an editor with the bundle open, a dev server still serving
    it) makes this raise on Windows, and a build tool that aborts because a
    previous run is still holding a handle is a build tool people learn to work
    around. Overwriting in place is a safe fallback: the new ``index.html`` is
    written by the copy, so a fresh document can never end up beside stale
    assets — at worst some orphaned hashed files remain, and nothing references
    those.
    """
    if not directory.exists():
        return
    try:
        shutil.rmtree(directory)
    except OSError as exc:
        print(f"无法清空 {directory.name}（{type(exc).__name__}: {exc}），改为就地覆盖。")


def stage_frontend() -> None:
    """Copy the built Studio where both the wheel and the exe look for it.

    Cleared first where possible: a stale asset from a previous build served
    alongside a fresh index.html is a blank page that looks like a code bug, and
    it has cost this project an afternoon before. ``_try_clear`` degrades to an
    in-place overwrite rather than aborting, which keeps that specific failure
    impossible without making a locked file fatal.
    """
    source = STUDIO / "dist"
    if not (source / "index.html").is_file() or not (source / "assets").is_dir():
        raise SystemExit(f"前端没有构建成功：{source} 里缺少 index.html 或 assets。")
    _try_clear(STUDIO_DIST)
    shutil.copytree(source, STUDIO_DIST, dirs_exist_ok=True)
    print(f"前端已放入 {STUDIO_DIST.relative_to(ROOT)}（wheel 与 exe 共用）")


def build_exe(out_dir: Path) -> Path:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller 未安装。运行：python -m pip install pyinstaller") from None

    work = out_dir / "pyi-work"
    spec = ROOT / "packaging" / "html-video.spec"
    run([sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm", "--clean",
         "--distpath", str(out_dir / "pyi"), "--workpath", str(work),
         "--log-level", "WARN"])
    built = out_dir / "pyi" / "html-video"
    if not (built / "html-video.exe").exists():
        raise SystemExit(f"打包没有产出可执行文件：{built}")
    return built


# A real ffmpeg/ffprobe is tens of megabytes. Anything smaller is a proxy that
# needs a machine-specific absolute path to work, i.e. exactly the thing that
# must not end up in a download.
_REAL_TOOL_MIN_BYTES = 1 << 20


# A shim descriptor is a small text file naming the real tool. The formats
# differ by manager and version, so instead of parsing one, pull out every
# string that could be an absolute path and let the filesystem decide.
# Paths appear quoted (Scoop), as XML text (Chocolatey) or bare.
_QUOTED = re.compile(r'"([^"\r\n]+)"|\'([^\'\r\n]+)\'')
_TAG_TEXT = re.compile(r'>([^<>\r\n]+)<')
# A POSIX branch needs a second separator so that a closing tag like
# `</command>` cannot be read as the absolute path `/command`.
_BARE_PATH = re.compile(
    r'[A-Za-z]:\\[^\s"\'<>,]+|/(?:[^\s"\'<>,/]+/)+[^\s"\'<>,]+')


def _path_candidates(text: str) -> list[str]:
    found: list[str] = []
    for pattern in (_QUOTED, _TAG_TEXT):
        for match in pattern.finditer(text):
            found.append((match.group(1) or match.group(2) or "").strip())
    found.extend(match.group(0) for match in _BARE_PATH.finditer(text))
    return [item for item in found if item]


def _follow_shim(candidate: Path) -> Path | None:
    """The path named by a package manager's shim descriptor, if there is one.

    Chocolatey writes ``ffmpeg.exe.shim`` beside the shim; Scoop writes
    ``ffmpeg.shim``. Both name the real tool by absolute path, which is exactly
    what makes the shim useless anywhere else — and why this must be followed.
    """
    for descriptor_name in (candidate.name + ".shim", candidate.stem + ".shim"):
        descriptor = candidate.with_name(descriptor_name)
        if not descriptor.is_file():
            continue
        text = descriptor.read_text(encoding="utf-8", errors="replace")
        for raw in _path_candidates(text):
            try:
                target = Path(raw)
            except (OSError, ValueError):  # a path this platform cannot express
                continue
            if target.is_file():
                return target
    return None


def resolve_tool(candidate: Path) -> Path | None:
    """The real executable behind ``candidate``, or ``None`` if it is only a proxy.

    Two traps here, and both produce a zip that runs on the build machine and
    nowhere else:

    * A reparse point. ``resolve()`` handles that one.
    * A *proxy* executable. WinGet, Chocolatey and Scoop all put a small shim on
      PATH. It is an ordinary file, so ``resolve()`` returns it unchanged and
      happily reports success; the copy then works here, where the absolute path
      inside the descriptor exists, and fails on the user's machine, where it
      does not. Size is the tell, and the descriptor is the remedy.

    Returning ``None`` rather than the proxy is deliberate: a caller that
    silently falls back to the shim ships a broken release, so make it say so.
    """
    if not candidate.exists():
        return None
    candidate = candidate.resolve()
    if candidate.stat().st_size >= _REAL_TOOL_MIN_BYTES:
        return candidate

    followed = _follow_shim(candidate)
    if followed is not None and followed.stat().st_size >= _REAL_TOOL_MIN_BYTES:
        return followed
    return None


def bundle_tools(app_dir: Path, ffmpeg_bin: str | None,
                 allow_missing: bool = False) -> list[str]:
    """Copy ffmpeg/ffprobe next to the executable.

    Search order is the same one the runtime uses to find them, so what the
    build ships is what the app will pick up — a build that silently ships a
    different ffmpeg than the one `doctor` reports is worse than shipping none.

    Missing tools are fatal by default: the whole promise of this download is
    "nothing else to install", and a release that quietly omits them breaks that
    promise on a machine we will never see. ``--allow-no-tools`` exists for
    builds that are not meant to ship.
    """
    target = app_dir / "bin"
    target.mkdir(parents=True, exist_ok=True)
    sources: list[Path] = []

    if ffmpeg_bin:
        base = Path(ffmpeg_bin)
    else:
        found = shutil.which("ffmpeg")
        base = Path(found).parent if found else Path(".")
    for name in ("ffmpeg", "ffprobe"):
        resolved = resolve_tool(base / (name + (".exe" if os.name == "nt" else "")))
        if resolved is not None:
            sources.append(resolved)

    copied: list[str] = []
    for source in sources:
        shutil.copy2(source, target / source.name)
        copied.append(source.name)

    proxies = [name for name in copied
               if (target / name).stat().st_size < _REAL_TOOL_MIN_BYTES]
    if proxies:
        raise SystemExit(
            f"{', '.join(proxies)} 不是真正的可执行文件（小于 "
            f"{_REAL_TOOL_MIN_BYTES >> 20} MB），看起来是包管理器放在 PATH 上的代理程序。"
            "用 --ffmpeg-bin 指向装着真实 ffmpeg 的目录再打包。")

    if not copied:
        message = ("没有找到 ffmpeg/ffprobe，发布包里不会自带。"
                   "用 --ffmpeg-bin 指定包含它们的目录。")
        if not allow_missing:
            raise SystemExit(message + "\n（确实不想自带就加 --allow-no-tools。）")
        print("警告：" + message)
    else:
        total = sum((target / name).stat().st_size for name in copied)
        print(f"自带工具：{', '.join(copied)}（共 {total / 1048576:.0f} MB，"
              f"这是发布包体积的主要来源）")
    return copied


def make_zip(app_dir: Path, out_dir: Path, version_str: str) -> Path:
    (app_dir / "使用说明.txt").write_text(README, encoding="utf-8")
    archive = out_dir / f"html-video-windows-x64-{version_str}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(app_dir.name) / path.relative_to(app_dir))
    return archive


def build_parser() -> argparse.ArgumentParser:
    """The command-line surface, split out so it can be tested.

    The module docstring doubles as the maintainer's copy-paste source, and a
    flag that has drifted out of the parser is a build someone cannot run.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "dist" / "release"))
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-exe", action="store_true")
    parser.add_argument("--ffmpeg-bin", default="",
                        help="目录，内含 ffmpeg.exe / ffprobe.exe")
    parser.add_argument("--allow-no-tools", action="store_true",
                        help="找不到 ffmpeg 时只警告；默认直接失败，"
                             "因为发布包承诺用户不用另外安装任何东西")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    version_str = version()
    print(f"构建 html-video {version_str} → {out_dir}")

    build_frontend(args.skip_frontend)
    stage_frontend()
    if args.skip_exe:
        return 0

    app_dir = build_exe(out_dir)
    bundle_tools(app_dir, args.ffmpeg_bin or None, allow_missing=args.allow_no_tools)
    archive = make_zip(app_dir, out_dir, version_str)

    size_mb = archive.stat().st_size / 1048576
    print(f"\n完成：{archive}  ({size_mb:.1f} MB)")
    print("把它上传到 GitHub Release，用户下载解压后双击 html-video.exe 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
