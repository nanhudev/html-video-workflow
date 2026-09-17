"""Measure the speech rate of the TTS engine this machine will actually use.

The pipeline has to know how long narration takes *before* it has any audio, so
it budgets against a constant. That constant is a property of the engine, not of
the language, and it is easy to get wrong: the value shipped for a long time was
off by more than half, which is why a request for 20 seconds produced a 32-second
video. Rather than trust a number somebody typed, run this and look.

    python scripts/measure_speech_rate.py            # default: whatever routes
    python scripts/measure_speech_rate.py --tts sapi # force one engine

It prints the aggregate rate and the per-sentence spread, then tells you what the
code currently assumes, so a drift shows up as a difference rather than as a
surprising video length.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

#: Sentences of deliberately different shapes, because rate depends on
#: punctuation and on how many ASCII/numeral characters are mixed in.
CJK_SAMPLES = [
    "你的数据，正在离开你的电脑。",
    "每一次提问，都被打包送进某个机房的服务器。你删掉对话，但副本通常还在。",
    "本地 AI 换了一条路：模型跑在你自己的机器上，问题不出门，答案直接返回。",
    "代价是你要先下载模型。你换来的，是数据不出本机、断网也能用、没有按月计费。",
    "所以问题不是哪个更强，而是哪些事，你愿意交给别人。",
    "人工智能正在改变我们工作和学习的方式。",
    "这条视频用一个例子说明，为什么延迟比吞吐量更重要。",
]

LATIN_SAMPLES = [
    "Your data is already leaving your computer.",
    "Every question you ask gets packaged up and sent to somebody else's server.",
    "Running the model locally means the question never leaves the machine.",
]


def _count_cjk(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _speak(provider, text: str, path: Path) -> float | None:
    from html_video_workflow.providers.base import NarrationSpec, TTSRequest

    try:
        provider.synthesize(
            TTSRequest(narration=NarrationSpec(text=text, language="zh-CN"),
                       output_path=str(path))
        )
    except Exception as exc:  # noqa: BLE001 - a probe must report, not crash
        print(f"  ! {type(exc).__name__}: {exc}")
        return None
    if not path.is_file():
        return None
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def _report(label: str, samples: list[str], provider, work: Path,
            counter) -> float | None:
    print(f"\n{label}")
    print("-" * 64)
    rates: list[float] = []
    total_units = 0.0
    total_seconds = 0.0
    for index, text in enumerate(samples):
        seconds = _speak(provider, text, work / f"{label}-{index}.wav")
        if seconds is None:
            continue
        units = counter(text)
        rate = units / seconds
        rates.append(rate)
        total_units += units
        total_seconds += seconds
        print(f"  {units:5.1f} units  {seconds:6.2f}s  {rate:5.2f}/s  {text[:30]}")
    if not rates:
        print("  no samples produced audio")
        return None
    aggregate = total_units / total_seconds
    print(f"  aggregate {aggregate:.2f}/s   median {statistics.median(rates):.2f}/s"
          f"   spread {min(rates):.2f}–{max(rates):.2f}")
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tts", default=None,
                        help="TTS provider id to probe (default: the routed one)")
    parser.add_argument("--work", default=None,
                        help="directory for the probe WAVs")
    args = parser.parse_args()

    from html_video_workflow.providers.registry import get as get_provider
    from html_video_workflow.utils.audio import (
        SAPI_CJK_CHARS_PER_SECOND,
        SAPI_LATIN_CHARS_PER_SECOND,
    )

    provider_id = args.tts
    if provider_id is None:
        # Route the request the way a real job would, so the rate measured is the
        # rate the pipeline will actually use on this machine.
        try:
            from html_video_workflow.pipeline.router import plan_pipeline

            plan = plan_pipeline(language="zh-CN", preset="auto")
            provider_id = (plan.get("tts") or {}).get("chosen") or "sapi"
        except Exception as exc:  # noqa: BLE001 - fall back to the always-present engine
            print(f"  (routing failed: {type(exc).__name__}; using sapi)")
            provider_id = "sapi"
    provider = get_provider(provider_id)
    print(f"probing TTS provider: {provider_id}")

    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="hvw-rate-"))
    work.mkdir(parents=True, exist_ok=True)

    cjk = _report("Chinese", CJK_SAMPLES, provider, work,
                  lambda t: float(_count_cjk(t)))
    latin = _report("Latin", LATIN_SAMPLES, provider, work,
                    lambda t: float(len(t.replace(" ", ""))))

    print("\n" + "=" * 64)
    print(f"CJK   measured {cjk if cjk else float('nan'):.2f}/s   "
          f"code assumes {SAPI_CJK_CHARS_PER_SECOND:.2f}/s")
    print(f"Latin measured {latin if latin else float('nan'):.2f}/s   "
          f"code assumes {SAPI_LATIN_CHARS_PER_SECOND:.2f}/s")
    if cjk and abs(cjk - SAPI_CJK_CHARS_PER_SECOND) / cjk > 0.15:
        print("\n  Drift is over 15%. Update utils/audio.py so the planner and the")
        print("  audio stage budget against this engine, not against the old one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
