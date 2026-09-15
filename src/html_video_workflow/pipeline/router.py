"""CapabilityResolver + ProviderRanker + PipelinePlanner.

The user picks a *preset*, not a model. Every decision comes back with human
readable reasons, including why a candidate was rejected.

**The rule that keeps this honest:** a preset is a set of *weights*, never a
mapping to a provider name. ``high_quality`` does not mean "pick Fish Speech" —
it means "weight naturalness above latency". The moment a preset names a
provider, the router stops being a router and becomes a lookup table that goes
stale every time a new engine ships.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.settings import RoutingSettings
from ..hardware.benchmark import get as get_benchmark, hardware_fingerprint
from ..hardware.profile import HardwareProfile, probe_hardware
from ..providers.base import Capability, ProviderType
from ..providers.registry import by_type, get as get_provider
from ..utils.logging import get_logger

log = get_logger("pipeline.router")


@dataclass(frozen=True)
class Weights:
    quality: float = 0.4
    speed: float = 0.3
    naturalness: float = 0.3
    startup_penalty: float = 1.0
    local_bonus: float = 0.8
    benchmark_bonus: float = 1.0
    #: Reward for honouring the requested language exactly rather than loosely.
    language_bonus: float = 1.5
    #: Reward for a provider whose features overlap what the request needs.
    feature_bonus: float = 0.9
    #: Penalty proportional to how far a provider exceeds the VRAM budget.
    vram_pressure: float = 0.0
    #: Extra weight on naturalness for speech specifically. Narration is judged
    #: by how human it sounds far more than by any other single axis.
    speech_naturalness: float = 0.0
    #: Weight of the penalty for deliberately low-fidelity providers (mocks).
    fidelity_penalty: float = 1.0


PRESETS: dict[str, Weights] = {
    "fast": Weights(quality=0.20, speed=0.55, naturalness=0.25, startup_penalty=2.0,
                    speech_naturalness=0.6, fidelity_penalty=0.0),
    "balanced": Weights(quality=0.40, speed=0.30, naturalness=0.30, startup_penalty=1.0,
                        speech_naturalness=1.2, fidelity_penalty=1.0),
    "high_quality": Weights(quality=0.55, speed=0.15, naturalness=0.30,
                            startup_penalty=0.4, speech_naturalness=2.0,
                            fidelity_penalty=3.0),
    "max_quality": Weights(quality=0.60, speed=0.05, naturalness=0.35,
                           startup_penalty=0.0, speech_naturalness=2.6,
                           fidelity_penalty=4.0),
}

STARTUP_PENALTY = {"low": 0.0, "medium": 0.8, "high": 1.8}

#: Quality tiers, translated to a 0–10 scale so they can be scored alongside
#: declared numbers. A provider that reports a tier but no score still routes
#: sensibly, which matters for adapters whose engines have not been benchmarked.
QUALITY_TIER_SCORE: dict[str, float] = {
    "none": 0.0,
    "robotic": 3.0,
    "basic": 4.5,
    "good": 6.5,
    "high": 8.0,
    "studio": 9.3,
}

#: Fallback chains; only used after a typed provider failure.
FALLBACKS: dict[str, list[str]] = {
    "tts": [
        "neural_sidecar", "aivisspeech", "openai_compatible_tts",
        "moss", "sapi", "mock_tts",
    ],
    "renderer": ["advanced_html", "legacy_html", "mock_renderer"],
    "llm": ["openai_compatible", "mock_llm"],
    "subtitle": ["srt"],
}


@dataclass
class Candidate:
    id: str
    score: float
    chosen: bool = False
    reason: list[str] = field(default_factory=list)
    capability: Capability | None = None


@dataclass
class RoutingDecision:
    stage: str
    preset: str
    selected: str | None
    candidates: list[Candidate]
    fallbacks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "preset": self.preset,
            "selected": self.selected,
            "candidates": [
                {
                    "id": c.id,
                    "score": round(c.score, 3),
                    "chosen": c.chosen,
                    "reason": c.reason,
                }
                for c in self.candidates
            ],
            "fallbacks": self.fallbacks,
        }


def resolve_preset(preset: str, hardware: HardwareProfile | None = None) -> str:
    """`auto` reads the machine; everything else passes through."""
    if preset != "auto":
        return preset
    hardware = hardware or probe_hardware()
    vram = hardware.vram_total_mb
    ram = hardware.ram_total_mb or 0
    if vram >= 12000 and ram >= 24000:
        return "high_quality"
    if vram >= 6000 and ram >= 12000:
        return "balanced"
    return "fast"


def _vram_budget(hardware: HardwareProfile) -> int:
    return int((hardware.vram_total_mb or 0) * 0.85)


def _language_match(provider_languages: list[str], requested: str | None) -> tuple[str, str | None]:
    """Classify a language match. Exact beats prefix beats miss.

    ``zh-CN`` vs a provider offering ``zh-TW`` is not a match — the same script
    with a different reading. Treating a prefix as sufficient is how a Chinese
    narration ends up read with the wrong phonology and nobody notices until
    someone who speaks the language listens.
    """
    if not requested:
        return "unconstrained", None
    if not provider_languages:
        return "unknown", "language support undeclared"
    if requested in provider_languages:
        return "exact", f"supports {requested}"
    short = requested.split("-")[0]
    # Only the script-level tag counts as a loose match (zh-CN vs zh).
    if short in provider_languages or any(
        str(lang) == short for lang in provider_languages
    ):
        return "prefix", f"supports {short} (region may differ)"
    return "none", f"does not support {requested}"


def _tts_quality_score(capability: Capability) -> tuple[float, list[str]]:
    """Resolve a scored quality value from whatever the provider reported.

    A provider may declare a numeric score, a tier, or only one of the two. The
    richer signal wins, but a missing one is never treated as zero — the
    difference between "scores 0" and "has not been scored" is the difference
    between rejecting a good engine and ranking it on what we do know.
    """
    reasons: list[str] = []
    tier = str(capability.details.get("quality_tier") or "").lower()
    tier_score = QUALITY_TIER_SCORE.get(tier)
    declared = capability.quality_score or 0.0
    if tier_score is not None and declared:
        reasons.append(f"quality tier {tier} ({declared:.1f})")
        return (tier_score + declared) / 2, reasons
    if tier_score is not None:
        reasons.append(f"quality tier {tier}")
        return tier_score, reasons
    if declared:
        reasons.append(f"declared quality {declared:.1f}")
        return declared, reasons
    reasons.append("quality unscored")
    return 5.0, reasons


def _naturalness_score(capability: Capability, tier: str) -> tuple[float, list[str]]:
    """Naturalness, the axis narration is actually judged on.

    When a provider gives only a tier, naturalness is approximated from it —
    a ``studio`` tier engine is natural by definition, a ``robotic`` one is not,
    and refusing to route at all because a number is missing would be worse than
    routing on the tier the provider did report.
    """
    reasons: list[str] = []
    tier_score = QUALITY_TIER_SCORE.get(tier)
    declared = capability.naturalness_score or 0.0
    if declared:
        reasons.append(f"naturalness {declared:.1f}")
        return declared, reasons
    if tier_score is not None:
        reasons.append(f"naturalness inferred from tier {tier}")
        return tier_score, reasons
    return 5.0, reasons


def _benchmark_bonus(provider_id: str, kind: str, fingerprint: str) -> tuple[float, str | None]:
    run = get_benchmark(f"{kind}::{provider_id}", fingerprint)
    if not run or not run.get("available"):
        return 0.0, "no benchmark yet — using declared scores"
    if kind == "tts":
        rtf = run.get("rtf")
        if isinstance(rtf, (int, float)) and rtf > 0:
            return max(0.0, 2.0 - rtf), f"benchmark RTF {rtf:.2f}"
    if kind == "renderer":
        ms = run.get("ms_per_scene")
        if isinstance(ms, (int, float)) and ms > 0:
            return max(0.0, 2.0 - ms / 1000.0), f"benchmark {ms:.0f} ms/scene"
    tps = run.get("tokens_per_second")
    if isinstance(tps, (int, float)) and tps > 0:
        return min(2.0, tps / 40.0), f"benchmark {tps:.1f} tok/s"
    return 0.5, "benchmark recorded"


def _tts_features(capability: Capability) -> dict[str, bool]:
    """Which optional speech features this provider can honour.

    Read from the descriptor details that the TTS adapters publish. Only an
    explicit ``yes`` counts: ``unknown`` is not support, and treating it as such
    would let a provider win a scoring round on a feature it may not have.
    """
    details = capability.details or {}
    keys = (
        "supports_emotion", "supports_style", "supports_voice_clone",
        "supports_streaming", "supports_speed", "supports_pitch",
        "supports_emphasis",
    )
    return {key: str(details.get(key, "unknown")).lower() == "yes" for key in keys}


def _is_low_fidelity(provider: Any, capability: Capability) -> bool:
    """True when a provider is a placeholder rather than a real engine.

    Read from the declared spec tags, because a tag is a claim the provider
    makes about itself and survives probing. ``low_fidelity`` is how a mock says
    "I am a guaranteed fallback, not a destination" — and a router that ignores
    it will happily pick a grey rectangle for a job that asked for a design.
    """
    tags = getattr(getattr(provider, "spec", None), "tags", None) or ()
    return "low_fidelity" in tags


def rank(
    provider_type: ProviderType | str,
    *,
    preset: str = "auto",
    language: str | None = None,
    hardware: HardwareProfile | None = None,
    routing: RoutingSettings | None = None,
    locked: str | None = None,
    kind: str | None = None,
    needs: list[str] | None = None,
) -> RoutingDecision:
    """Score every provider of a type and return the best available one.

    ``needs`` names the optional features the request actually uses (``emotion``,
    ``style``, ...). A provider that cannot supply one is not disqualified — the
    stage still has to run — but it scores lower and says so, which is how a
    downranked provider stays visible in the explanation instead of vanishing.
    """
    kind = kind or str(ProviderType(provider_type).value)
    hardware = hardware or probe_hardware()
    routing = routing or RoutingSettings()
    preset = resolve_preset(preset, hardware)
    weights = PRESETS.get(preset, PRESETS["balanced"])
    fingerprint = hardware_fingerprint(hardware)
    vram_budget = _vram_budget(hardware)
    needs = needs or []

    candidates: list[Candidate] = []
    for provider in by_type(provider_type):
        reasons: list[str] = []
        score = 0.0
        try:
            capability: Capability = provider.capabilities()
        except Exception as exc:  # pragma: no cover - defensive
            candidates.append(
                Candidate(id=provider.id, score=-1, reason=[f"probe error: {exc}"])
            )
            continue

        if locked and provider.id == locked:
            candidates.append(
                Candidate(
                    id=provider.id,
                    score=1000.0,
                    chosen=True,
                    reason=["locked by user override", *([f"state={capability.state.value}"]
                                                          if not capability.available else [])],
                    capability=capability,
                )
            )
            continue

        if not capability.available:
            # Name the blocker explicitly. "Rejected" without a reason is how a
            # user ends up staring at a disabled row with no idea what to fix.
            state = capability.state.value
            blame = {
                "missing_credentials": "credentials",
                "not_installed": "not installed",
                "unavailable": "unavailable",
                "unsupported": "unsupported on this OS",
            }.get(state, state)
            reason = capability.reason or f"state={state}"
            if state == "missing_credentials" and "credential" not in reason.lower():
                reason = f"missing credentials — {reason}"
            candidates.append(
                Candidate(
                    id=provider.id,
                    score=-1,
                    reason=[reason],
                    capability=capability,
                )
            )
            log.debug("rejected %s (%s): %s", provider.id, blame, reason)
            continue

        match, language_note = _language_match(capability.languages, language)
        if match == "none":
            candidates.append(
                Candidate(
                    id=provider.id,
                    score=-1,
                    reason=[language_note or f"does not support {language}"],
                    capability=capability,
                )
            )
            continue
        if language_note:
            reasons.append(language_note)
            if match == "exact":
                score += weights.language_bonus

        if not routing.allow_api and not capability.local:
            candidates.append(
                Candidate(
                    id=provider.id,
                    score=-1,
                    reason=["API providers disabled by settings"],
                    capability=capability,
                )
            )
            continue

        if capability.estimated_vram_mb > vram_budget:
            candidates.append(
                Candidate(
                    id=provider.id,
                    score=-1,
                    reason=[
                        f"needs ~{capability.estimated_vram_mb}MB VRAM, "
                        f"budget {vram_budget}MB"
                    ],
                    capability=capability,
                )
            )
            continue

        tier = str(capability.details.get("quality_tier") or "").lower()
        quality_value, quality_reasons = _tts_quality_score(capability)
        naturalness_value, naturalness_reasons = _naturalness_score(capability, tier)
        reasons += quality_reasons + naturalness_reasons

        score += weights.quality * quality_value
        score += weights.speed * (capability.speed_score or 5.0)
        score += weights.naturalness * naturalness_value
        # Narration quality is dominated by how human it sounds, so for TTS the
        # speech-specific weighting stacks on top of the generic one. Without
        # this, a fast robotic engine can out-score a natural one under
        # `balanced`, which is precisely the tradeoff a user did not ask for.
        if kind == "tts":
            score += weights.speech_naturalness * naturalness_value
        score -= weights.startup_penalty * STARTUP_PENALTY.get(capability.startup_cost, 1.0)

        if capability.local and routing.prefer_local:
            score += weights.local_bonus
            reasons.append("runs locally")
        elif not capability.local:
            reasons.append("remote API")

        if needs:
            features = _tts_features(capability)
            supported = [name for name in needs if features.get(f"supports_{name}")]
            missing = [name for name in needs if name not in supported]
            if supported:
                score += weights.feature_bonus * len(supported)
                reasons.append(f"supports requested: {', '.join(supported)}")
            if missing:
                # Not fatal, but the user must be able to see that a request for
                # emotion was routed to an engine that will drop it.
                reasons.append(f"cannot apply: {', '.join(missing)}")

        bonus, note = _benchmark_bonus(provider.id, kind, fingerprint)
        score += weights.benchmark_bonus * bonus
        if note:
            reasons.append(note)

        # Low-fidelity providers (mocks and placeholders) must never win a
        # quality-oriented preset on raw speed. They stay in the pool as a
        # guaranteed last resort, but they rank last whenever the user asked for
        # fidelity — and the reason says so, so the ranking is never mysterious.
        if _is_low_fidelity(provider, capability):
            score -= weights.fidelity_penalty
            reasons.append("low-fidelity placeholder provider")

        if capability.voices:
            reasons.append(f"{len(capability.voices)} voices detected")
        if capability.gpu:
            reasons.append(f"~{capability.estimated_vram_mb}MB VRAM")

        candidates.append(
            Candidate(id=provider.id, score=score, reason=reasons, capability=capability)
        )

    usable = [c for c in candidates if c.score >= 0]
    usable.sort(key=lambda c: c.score, reverse=True)
    if usable:
        usable[0].chosen = True
    selected = usable[0].id if usable else None
    if not selected:
        log.warning("no provider available for stage %s under preset %s", kind, preset)
    return RoutingDecision(
        stage=kind,
        preset=preset,
        selected=selected,
        candidates=candidates,
        fallbacks=_fallback_order(kind, selected, candidates),
    )


def _fallback_order(
    kind: str, selected: str | None, candidates: list[Candidate]
) -> list[str]:
    """The order we would try if the selected provider fails at run time.

    Declared chains come first because they encode a deliberate degradation
    (neural → API → system), then anything else that probed as available, so a
    project is not stranded merely because its engine was not in the list.
    """
    chain = [pid for pid in FALLBACKS.get(kind, []) if pid != selected]
    available = {
        c.id for c in candidates if c.score >= 0 and c.id != selected
    }
    ordered = [pid for pid in chain if pid in available]
    ordered += sorted(available - set(ordered))
    return ordered


def plan_pipeline(
    *,
    language: str = "zh-CN",
    preset: str = "auto",
    hardware: HardwareProfile | None = None,
    routing: RoutingSettings | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Decide the full provider chain for one render job."""
    hardware = hardware or probe_hardware()
    routing = routing or RoutingSettings()
    routing.locked_providers.update(overrides or {})
    preset = resolve_preset(preset, hardware)

    decisions = {}
    for stage, provider_type in (
        ("llm", ProviderType.LLM),
        ("tts", ProviderType.TTS),
        ("renderer", ProviderType.RENDERER),
        ("subtitle", ProviderType.SUBTITLE),
    ):
        decision = rank(
            provider_type,
            preset=preset,
            language=language,
            hardware=hardware,
            routing=routing,
            locked=routing.locked_providers.get(stage),
            kind=stage,
        )
        decisions[stage] = decision

    return {
        "preset": preset,
        "hardware": {
            "cpu": hardware.cpu_model,
            "cores": hardware.cpu_logical_cores,
            "ram_mb": hardware.ram_total_mb,
            "gpus": [g.model for g in hardware.gpus],
            "vram_mb": hardware.vram_total_mb,
        },
        "selection": {stage: decision.selected for stage, decision in decisions.items()},
        "reasons": {stage: decision.to_dict() for stage, decision in decisions.items()},
        "fallbacks": {stage: decision.fallbacks for stage, decision in decisions.items()},
    }


_STAGE_TYPES: dict[str, ProviderType] = {
    "tts": ProviderType.TTS,
    "llm": ProviderType.LLM,
    "renderer": ProviderType.RENDERER,
    "subtitle": ProviderType.SUBTITLE,
    "avatar": ProviderType.AVATAR,
    "image": ProviderType.IMAGE,
    "asset": ProviderType.ASSET,
}


def provider_for(stage: str, selected_id: str | None = None, fallback_index: int = 0):
    """Return a concrete provider instance for a stage.

    ``fallback_index`` walks the declared fallback chain and is only used after a
    typed provider failure — and the substitution is always recorded upstream.
    """
    if fallback_index:
        chain = FALLBACKS.get(stage, [])
        if fallback_index - 1 < len(chain):
            return get_provider(chain[fallback_index - 1])
    if selected_id:
        return get_provider(selected_id)
    provider_type = _STAGE_TYPES.get(stage)
    if provider_type is None:
        raise ValueError(f"unknown stage {stage}")
    for provider in by_type(provider_type):
        if provider.probe().available:
            return provider
    raise ValueError(f"no available provider for stage {stage}")
