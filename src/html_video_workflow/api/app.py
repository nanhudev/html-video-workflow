"""FastAPI application factory.

The API is a transport layer only — every endpoint delegates to the Runtime,
which is exactly what the CLI, MCP adapter and Studio do.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from ..config.settings import load_env_file, load_settings


def create_app() -> FastAPI:
    load_env_file()
    settings = load_settings()
    app = FastAPI(
        title="HTML Video Workflow Runtime",
        version=__version__,
        description=(
            "Local-first agentic video production runtime: "
            "agent decides, IR describes, providers execute, runtime schedules, "
            "quality verifies."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .routes import projects, system, v1
    from .studio import mount_studio

    app.include_router(system.router)
    app.include_router(projects.router)
    app.include_router(v1.router)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    # Mounted after every router: a static mount at "/" claims all remaining
    # paths, and the API must win. `None` means the frontend was never built,
    # which the CLI reports rather than serving a blank page.
    app.state.studio_dir = mount_studio(app)
    app.state.settings = settings
    return app
