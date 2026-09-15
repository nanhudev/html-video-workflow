"""LocalAssetProvider — resolve user-supplied files into provenance records."""
from __future__ import annotations

from pathlib import Path

from ...utils.hashing import hash_file
from ..base import (
    AssetProvider,
    ProbeResult,
    ProbeState,
    ProviderResult,
    ProviderSpec,
)
from ..registry import register


@register
class LocalAssetProvider(AssetProvider):
    spec = ProviderSpec(
        id="local_asset",
        type="asset",
        name="Local Assets",
        vendor="html-video-workflow",
        version="1.0.0",
        local=True,
        implementation="inprocess",
        quality_score=8.0,
        speed_score=9.0,
        naturalness_score=8.0,
        startup_cost="low",
        install_state="builtin",
        tags=["local", "provenance"],
    )

    def probe(self) -> ProbeResult:
        return ProbeResult(state=ProbeState.READY, reason="Filesystem always available")

    def resolve(self, request: dict) -> ProviderResult:
        raw = request.get("path")
        if not raw:
            return ProviderResult(ok=False, provider=self.id, message="missing path")
        path = Path(raw)
        if not path.exists():
            return ProviderResult(ok=False, provider=self.id, message=f"not found: {path}")
        return ProviderResult(
            provider=self.id,
            artifacts={"path": str(path.resolve())},
            metrics={
                "sha256": hash_file(path),
                "size_bytes": path.stat().st_size,
                "kind": request.get("kind") or "unknown",
            },
        )
