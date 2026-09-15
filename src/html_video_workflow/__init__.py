"""HTML Video Workflow — local-first agentic video production runtime.

Principle: the agent decides what should be shown, the IR describes what the
video means, providers decide how capabilities are executed, the runtime picks
the best available pipeline, and the quality system decides whether the result
is acceptable.

One prompt in, one MP4 out::

    from html_video_workflow import create_video

    result = create_video(prompt="explain vector databases", platform="youtube_16x9")
    print(result.video_path)
"""
from __future__ import annotations

__version__ = "0.3.0"


def create_video(*args, **kwargs):
    """Make a video. This is the whole Python API.

    Accepts either a :class:`~html_video_workflow.core.request.CreateVideoRequest`
    or the same fields as keyword arguments, and returns a
    :class:`~html_video_workflow.core.request.VideoResult`. It is a thin wrapper:
    every decision is made by ``VideoRuntime.create_video``, which the CLI, the
    REST API, MCP and the Studio also call.

    >>> create_video(prompt="explain vector databases").video_path  # doctest: +SKIP
    """
    from .config.settings import load_env_file
    from .core.request import CreateVideoRequest
    from .runtime.engine import get_runtime

    load_env_file()
    request = args[0] if args and isinstance(args[0], CreateVideoRequest) else \
        CreateVideoRequest(**kwargs)
    return get_runtime().create_video(request)


def suggest_topics(prompt: str | None = None, *, count: int = 5, **kwargs):
    """Candidate angles for a topic. Offline and deterministic."""
    from .core.request import CreateVideoRequest
    from .planning.topic_planner import TopicPlanner

    return TopicPlanner().suggest(CreateVideoRequest(prompt=prompt or "", **kwargs),
                                  count=count)


__all__ = ["__version__", "create_video", "suggest_topics"]
