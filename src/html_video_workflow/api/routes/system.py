"""System endpoints: hardware, providers, benchmarks, settings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ... import __version__
from ...config.paths import hv_home, outputs_dir
from ...config.settings import known_secrets, load_settings
from ...hardware.benchmark import load_benchmarks, run_core_benchmarks
from ...hardware.profile import probe_hardware
from ...pipeline.router import plan_pipeline
from ...providers.base import ProviderType
from ...providers.registry import capabilities, get as get_provider

router = APIRouter(prefix="", tags=["system"])


@router.get("/system")
def get_system() -> dict[str, Any]:
    settings = load_settings()
    return {
        "version": __version__,
        "home": str(hv_home()),
        "outputs": str(outputs_dir()),
        "settings": settings.model_dump(),
        "secrets": {k: v for k, v in known_secrets().items() if v},
    }


@router.get("/hardware")
def get_hardware(refresh: bool = False) -> dict[str, Any]:
    profile = probe_hardware(use_cache=not refresh)
    return profile.to_dict()


@router.get("/providers")
def list_providers(provider_type: str | None = None) -> list[dict[str, Any]]:
    rows = capabilities()
    if provider_type:
        try:
            wanted = ProviderType(provider_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown type {provider_type}") from exc
        rows = [row for row in rows if row.type == wanted]
    return [row.model_dump(mode="json") for row in rows]


@router.get("/providers/{provider_id}/probe")
@router.post("/providers/{provider_id}/probe")
def probe_provider(provider_id: str) -> dict[str, Any]:
    """Probe one provider and return spec + real probe state + capability.

    Exposed on both GET and POST: probing is a read (it may spawn a subprocess,
    but it never mutates user data), so a plain link should work. POST stays for
    clients that prefer it.
    """
    try:
        provider = get_provider(provider_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = provider.probe()
    return {
        "id": provider_id,
        "spec": provider.spec.model_dump(mode="json"),
        "probe": result.model_dump(mode="json"),
        "capability": provider.capabilities().model_dump(mode="json"),
    }


@router.get("/routing")
def get_routing(preset: str = "auto", language: str = "zh-CN") -> dict[str, Any]:
    """Explain which pipeline would be chosen, and why."""
    return plan_pipeline(language=language, preset=preset)


@router.get("/benchmarks")
def get_benchmarks() -> dict[str, Any]:
    return load_benchmarks()


@router.post("/benchmarks/run")
def run_benchmarks() -> dict[str, Any]:
    return run_core_benchmarks()
