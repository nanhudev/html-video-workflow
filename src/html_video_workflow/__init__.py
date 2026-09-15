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

__version__ = "0.4.0"


def _as_request(model, args: tuple, kwargs: dict):
    """Turn whatever the caller passed into one request object.

    Three shapes are accepted, and the README advertises all three::

        create_video("why local AI matters")
        create_video(prompt="why local AI matters", duration_sec=30)
        create_video(CreateVideoRequest(prompt="..."))

    Everything else is refused loudly. A positional prompt used to be *ignored*
    silently — ``create_video("a prompt")`` built a request with no intent and
    failed with "nothing to make a video from", which points the caller at the
    wrong problem entirely. A misspelled field is refused for the same reason:
    with ``extra="allow"`` on the model, ``create_video(prompt="x", output="a.mp4")``
    would have looked like it worked and quietly written somewhere else.
    """
    if len(args) > 1:
        raise TypeError(
            f"{model.__name__}: at most one positional argument is accepted "
            f"(a prompt or a request object), got {len(args)}")

    if args:
        first = args[0]
        if isinstance(first, model):
            if kwargs:
                raise TypeError(
                    "pass either a request object or keyword fields, not both")
            return first
        if isinstance(first, str):
            if "prompt" in kwargs:
                raise TypeError("prompt given both positionally and by keyword")
            kwargs = {**kwargs, "prompt": first}
        else:
            raise TypeError(
                "the first positional argument must be a prompt string or a "
                f"{model.__name__}, got {type(first).__name__}")

    unknown = sorted(set(kwargs) - set(model.model_fields))
    if unknown:
        raise TypeError(
            "unknown field(s): " + ", ".join(unknown) + ". Valid fields are: "
            + ", ".join(sorted(model.model_fields)))
    return model(**kwargs)


def create_video(*args, **kwargs):
    """Make a video. This is the whole Python API.

    Accepts a prompt, a :class:`~html_video_workflow.core.request.CreateVideoRequest`,
    or the request's fields as keyword arguments, and returns a
    :class:`~html_video_workflow.core.request.VideoResult`. It is a thin wrapper:
    every decision is made by ``VideoRuntime.create_video``, which the CLI, the
    REST API, MCP and the Studio also call.

    >>> create_video("explain vector databases").video_path          # doctest: +SKIP
    >>> create_video(prompt="explain vector databases").video_path   # doctest: +SKIP
    """
    from .config.settings import load_env_file
    from .core.request import CreateVideoRequest
    from .runtime.engine import get_runtime

    load_env_file()
    return get_runtime().create_video(_as_request(CreateVideoRequest, args, kwargs))


def suggest_topics(prompt: str | None = None, *, count: int = 5, **kwargs):
    """Candidate angles for a topic. Offline and deterministic."""
    from .core.request import CreateVideoRequest
    from .planning.topic_planner import TopicPlanner

    return TopicPlanner().suggest(CreateVideoRequest(prompt=prompt or "", **kwargs),
                                  count=count)


__all__ = ["__version__", "create_video", "suggest_topics"]
