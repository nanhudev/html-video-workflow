"""Advanced renderer subsystem.

Deliberately split into focused modules rather than one large renderer file:

| Module | Responsibility |
| --- | --- |
| `scene_compiler` | IR V2 scene → standalone document |
| `layout` | five composable primitives |
| `motion` | nine primitives with computed per-layer timing |
| `layer` | one IR layer → markup |
| `typography` | six-role type system |
| `aspect` | ratios and platform safe areas |
| `assets` | asset resolution with honest failure |
| `capture` | browser screenshot / print-to-frame strategies |
| `service` | `BrowserRenderService` abstraction |
| `determinism` | reproducible rendering |
| `critic` | rule-driven critique (no scores) |

The split exists because these change for different reasons. A new platform's
safe area touches only `aspect`; a new easing touches only `motion`; supporting a
new browser touches only `capture`. In a single 900-line renderer, all three
changes land in one file and start conflicting.
"""
from __future__ import annotations

from .aspect import AspectSpec, SafeArea, aspect_for, safe_area_for
from .assets import AssetResolver, MissingAsset, ResolvedAsset
from .capture import BrowserCapture, CaptureResult, capture_strategies
from .critic import (
    CritiqueReport,
    Finding,
    SceneFacts,
    SceneVariationPolicy,
    VisualDesignCritic,
    contrast_ratio,
)
from .determinism import RenderSeed, validate_document
from .layout import LayoutEngine, LayoutResult, Slot, supported_layouts
from .layer import LayerRenderer
from .motion import MotionEngine, TimingPlan, supported_motions
from .scene_compiler import CompiledScene, SceneCompiler
from .service import BrowserRenderService
from .typography import TypographyProfile, get_profile

__all__ = [
    "AspectSpec", "SafeArea", "aspect_for", "safe_area_for",
    "AssetResolver", "MissingAsset", "ResolvedAsset",
    "BrowserCapture", "CaptureResult", "capture_strategies",
    "CritiqueReport", "Finding", "SceneFacts", "SceneVariationPolicy",
    "VisualDesignCritic", "contrast_ratio",
    "RenderSeed", "validate_document",
    "LayoutEngine", "LayoutResult", "Slot", "supported_layouts",
    "LayerRenderer",
    "MotionEngine", "TimingPlan", "supported_motions",
    "CompiledScene", "SceneCompiler",
    "BrowserRenderService",
    "TypographyProfile", "get_profile",
]
