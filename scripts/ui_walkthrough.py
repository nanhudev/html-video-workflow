"""Drive the Studio in a real browser and screenshot every wizard step.

Why this exists: the project has **no automated look at the interface**. The
pytest suite asserts on data structures, and it passed 243/243 while a headline
was printing on top of a label — placement-without-overlap is a property no
metric checks. The same is true of the wizard: "the button is there in the
response object" and "a human can find the button" are different claims.

So this walks the actual flow in Edge via the DevTools protocol — real clicks,
real typing, real screenshots — and fails loudly if a step does not appear.

Usage::

    python scripts/ui_walkthrough.py --url http://127.0.0.1:8899 \\
        --out D:/hvw-tmp/ui-shots
    python scripts/ui_walkthrough.py --render      # go all the way to a video

Without ``--render`` it stops at the confirmation screen, which takes seconds.
``--render`` starts a real job and waits for it, which takes minutes.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
)

VIEWPORT = (1440, 1000)


# ------------------------------------------------------------------ CDP client
class Browser:
    """Minimal DevTools-protocol client. Enough to click, type and screenshot."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._id = 0
        self._ws = None
        self._target_id = ""

    # -------------------------------------------------------------- lifecycle
    def open(self, url: str, timeout: float = 30.0) -> None:
        import websockets.sync.client as ws_client  # type: ignore

        target = self._new_target(url, timeout)
        self._target_id = target["id"]
        self._ws = ws_client.connect(target["webSocketDebuggerUrl"],
                                     max_size=64 * 1024 * 1024)
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride",
                  width=VIEWPORT[0], height=VIEWPORT[1],
                  deviceScaleFactor=1, mobile=False)

    def _new_target(self, url: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/json/new?{url}", method="PUT")
                with urllib.request.urlopen(request, timeout=5) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # Older builds only accept GET; the deprecation is not our problem.
                if exc.code in (405, 404):
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{self.port}/json/new?{url}",
                            timeout=5) as response:
                        return json.loads(response.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - the daemon is still booting
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(0.4)
        raise RuntimeError(f"could not create a browser target: {last}")

    def close(self) -> None:
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/json/close/{self._target_id}",
                timeout=3).read()
        except Exception:  # noqa: BLE001
            pass

    # ----------------------------------------------------------------- calls
    def call(self, method: str, **params) -> dict:
        self._id += 1
        message = {"id": self._id, "method": method, "params": params}
        assert self._ws is not None
        self._ws.send(json.dumps(message))
        while True:
            raw = self._ws.recv(timeout=60)
            payload = json.loads(raw)
            if payload.get("id") == self._id:
                if "error" in payload:
                    raise RuntimeError(f"{method}: {payload['error']}")
                return payload.get("result", {})

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 20.0,
                 label: str = "") -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.evaluate(expression):
                return True
            time.sleep(0.3)
        raise RuntimeError(f"timed out waiting for {label or expression}")

    def goto(self, url: str) -> None:
        """Navigate and wait for the document, not for networkidle.

        The Studio polls while a job runs, so "idle" never arrives.
        """
        self.call("Page.navigate", url=url)
        self.wait_for("document.readyState === 'complete'", label="page load")

    def screenshot(self, path: Path) -> None:
        payload = self.call("Page.captureScreenshot", format="png",
                            captureBeyondViewport=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(payload["data"]))


# --------------------------------------------------------------- interactions
CLICK_BY_TEXT = """
(() => {
  const wanted = %s;
  const nodes = [...document.querySelectorAll('button, .wz-choice, .wz-step, .nav, .wz-chip')];
  const hit = nodes.find(n => (n.textContent || '').includes(wanted));
  if (!hit) return false;
  hit.click();
  return true;
})()
"""

SET_INPUT = """
(() => {
  const el = document.querySelector(%s);
  if (!el) return false;
  const proto = el.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, %s);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
})()
"""


def click_text(browser: Browser, text: str) -> None:
    if not browser.evaluate(CLICK_BY_TEXT % json.dumps(text, ensure_ascii=False)):
        raise RuntimeError(f"no clickable element containing {text!r}")


def fill(browser: Browser, selector: str, value: str) -> None:
    if not browser.evaluate(SET_INPUT % (json.dumps(selector), json.dumps(value))):
        raise RuntimeError(f"no input matching {selector}")


# ---------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8899")
    parser.add_argument("--out", default="ui-shots")
    parser.add_argument("--topic", default="为什么本地跑的 AI 更安全")
    parser.add_argument("--render", action="store_true",
                        help="actually generate a video and screenshot the result")
    parser.add_argument("--quick", action="store_true",
                        help="pick 30s + 1:1 so a --render run finishes sooner")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="how long to wait for a render")
    parser.add_argument("--edge", default="")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args(argv)

    out = Path(args.out)
    edge = args.edge or next((p for p in EDGE_CANDIDATES if Path(p).exists()), "")
    if not edge and not shutil.which("msedge"):
        print("找不到 Edge/Chrome。用 --edge 指定路径。")
        return 2

    profile = out / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        edge or "msedge",
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--hide-scrollbars",
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile}",
        f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}",
    ]
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    browser = Browser(args.port)
    shots: list[str] = []
    try:
        browser.open("about:blank")
        browser.goto(f"{args.url}/#create/0")
        browser.wait_for("!!document.querySelector('.wz-steps')", label="向导外壳")
        time.sleep(1.5)
        browser.screenshot(out / "01-selfcheck.png")
        shots.append("01-selfcheck.png")

        click_text(browser, "下一步")
        time.sleep(0.6)
        click_text(browser, "接入自己的 AI")
        time.sleep(0.6)
        click_text(browser, "DeepSeek")
        time.sleep(0.4)
        fill(browser, "input[type=password]", "sk-walkthrough-not-a-real-key")
        time.sleep(0.4)
        browser.screenshot(out / "02-api-form.png")
        shots.append("02-api-form.png")

        click_text(browser, "下一步")  # 选题
        time.sleep(0.6)
        fill(browser, "textarea", args.topic)
        click_text(browser, "帮我想几个角度")
        browser.wait_for(
            "[...document.querySelectorAll('.wz-choice')].length > 3",
            timeout=25, label="角度建议")
        if args.quick:
            # 30s at 1:1 is about a quarter of the pixels of a 60s 1080p run.
            # Same code path, a fraction of the wait.
            click_text(browser, "30 秒")
            time.sleep(0.3)
            click_text(browser, "方形 1:1")
            time.sleep(0.3)
        browser.screenshot(out / "03-topic.png")
        shots.append("03-topic.png")

        click_text(browser, "下一步")  # 写作风格
        time.sleep(0.6)
        click_text(browser, "科普解说")
        time.sleep(0.6)
        browser.screenshot(out / "04-preset.png")
        shots.append("04-preset.png")

        click_text(browser, "下一步")  # 模板与配色
        time.sleep(0.6)
        browser.screenshot(out / "05-look.png")
        shots.append("05-look.png")

        click_text(browser, "下一步")  # 生成
        time.sleep(0.6)
        browser.screenshot(out / "06-confirm.png")
        shots.append("06-confirm.png")

        if not args.render:
            print("停在确认页（未加 --render）。")
            return _report(out, shots)

        click_text(browser, "开始生成")
        browser.wait_for("!!document.querySelector('.wz-progress')", timeout=60,
                         label="进度条")
        time.sleep(4)
        browser.screenshot(out / "07-running.png")
        shots.append("07-running.png")

        deadline = time.time() + args.timeout
        while time.time() < deadline:
            done = browser.evaluate("!!document.querySelector('.wz-video')")
            failed = browser.evaluate(
                "!!document.querySelector('.wz-alert.bad')")
            if done:
                break
            if failed:
                text = browser.evaluate(
                    "document.querySelector('.wz-alert.bad').textContent")
                browser.screenshot(out / "08-failed.png")
                print(f"渲染失败：{text}")
                return 1
            time.sleep(3)
        else:
            browser.screenshot(out / "08-timeout.png")
            print(f"{args.timeout:.0f} 秒内没有完成。")
            return 1

        time.sleep(2)
        browser.screenshot(out / "08-result.png")
        shots.append("08-result.png")
        print("结果页已截图。")

        browser.goto(f"{args.url}/#works")
        browser.wait_for("!!document.querySelector('.wz-works')", label="作品页")
        time.sleep(1.5)
        browser.screenshot(out / "09-works.png")
        shots.append("09-works.png")
        return _report(out, shots)
    finally:
        if not args.keep_open:
            browser.close()
            proc.terminate()


def _report(out: Path, shots: list[str]) -> int:
    print(f"{len(shots)} 张截图 → {out}")
    for name in shots:
        path = out / name
        print(f"  {name}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
