"""TTS provider contract tests.

No model is downloaded and no paid API is called. Network adapters are tested
against an in-process stub HTTP server, which is what makes it possible to prove
the *mapping* is correct without owning a GPU.

What these tests are for: the contract is the only thing standing between "the
router picked a provider" and "the audio is correct". A silently dropped emotion
or a leaked API key is invisible in a green E2E render, so it gets tested here.
"""
from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from html_video_workflow.providers.base import ProbeState, ProviderType
from html_video_workflow.providers.registry import by_type, ensure_loaded, get, load_failures
from html_video_workflow.providers.tts.contract import (
    AudioFormat,
    CapabilityFlag,
    GPURequirement,
    QualityTier,
    TTSRequest,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def stub_server():
    """A configurable stub standing in for a real TTS service."""
    state: dict = {"routes": {}, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _respond(self, method: str) -> None:
            body = b""
            if "Content-Length" in self.headers:
                body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append(
                {
                    "method": method,
                    "path": self.path,
                    "body": json.loads(body) if body else None,
                    "headers": dict(self.headers),
                }
            )
            route = state["routes"].get(self.path.split("?")[0])
            if route is None:
                self.send_response(404)
                self.end_headers()
                return
            status, payload, content_type = route
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(payload if isinstance(payload, bytes) else payload.encode())

        def do_GET(self):
            self._respond("GET")

        def do_POST(self):
            self._respond("POST")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["base_url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


def _tiny_wav() -> bytes:
    """A valid, near-silent WAV the providers can measure."""
    import io
    import struct
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(struct.pack("<h", 0) * 2205)  # 0.1 s
    return buffer.getvalue()


# ------------------------------------------------------------------ registry
def test_all_tts_adapters_load_without_failures():
    ensure_loaded()
    assert load_failures() == {}, "a provider module failed to import"


def test_at_least_four_tts_adapters_registered():
    ensure_loaded()
    ids = {p.id for p in by_type(ProviderType.TTS)}
    assert {"sapi", "mock_tts", "aivisspeech", "openai_compatible_tts"} <= ids
    assert len(ids) >= 4


# ------------------------------------------------------------------- aivis
def test_aivisspeech_reports_unavailable_when_engine_down(monkeypatch):
    """A stopped engine is a state, not an exception. This is the whole point."""
    monkeypatch.setenv("HVW_AIVIS_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HVW_AIVIS_TIMEOUT", "1")
    provider = get("aivisspeech")
    result = provider.probe()
    assert result.state is ProbeState.UNAVAILABLE
    assert not result.available
    assert "not reachable" in result.reason


def test_aivisspeech_probe_reads_engine_manifest(stub_server, monkeypatch):
    stub_server["routes"]["/engine_manifest"] = (
        200,
        json.dumps({"engine_version": "1.2.3", "brand_name": "AivisSpeech"}),
        "application/json",
    )
    stub_server["routes"]["/speakers"] = (
        200,
        json.dumps(
            [{"name": "Anneli", "styles": [{"id": 888753760, "name": "Normal"}]}]
        ),
        "application/json",
    )
    monkeypatch.setenv("HVW_AIVIS_BASE_URL", stub_server["base_url"])

    provider = get("aivisspeech")
    result = provider.probe()
    assert result.state is ProbeState.READY
    assert "1.2.3" in result.reason
    assert result.evidence["styles"] == 1

    voices = provider.list_voices()
    assert [v.id for v in voices] == ["888753760"]

    descriptor = provider.descriptor()
    assert descriptor.available is CapabilityFlag.YES
    assert descriptor.voice_count == 1
    assert descriptor.supports_style is CapabilityFlag.YES
    assert descriptor.supports_emotion is CapabilityFlag.NO


def test_aivisspeech_synthesis_posts_query_then_synthesis(stub_server, monkeypatch):
    stub_server["routes"]["/audio_query"] = (
        200,
        json.dumps(
            {
                "speedScale": 1.0,
                "prePhonemeLength": 0.1,
                "postPhonemeLength": 0.1,
                "accent_phrases": [
                    {"accent": 1, "moras": [{"text": "こ", "pitch": 5.0}]}
                ],
            }
        ),
        "application/json",
    )
    stub_server["routes"]["/synthesis"] = (200, _tiny_wav(), "audio/wav")
    monkeypatch.setenv("HVW_AIVIS_BASE_URL", stub_server["base_url"])

    stub_server["requests"].clear()
    provider = get("aivisspeech")
    output = None
    import tempfile
    from pathlib import Path

    output = Path(tempfile.mkdtemp()) / "scene.wav"
    response = provider.synthesize(
        TTSRequest(
            text="これはテストです。",
            language="ja-JP",
            voice="888753760",
            speed=1.15,
            pause_after_ms=300,
            output_path=str(output),
        )
    )
    assert response.audio_path and Path(response.audio_path).exists()

    paths = [r["path"] for r in stub_server["requests"]]
    assert "/audio_query" in paths
    assert any(p.startswith("/synthesis") for p in paths)

    query_body = next(
        r["body"] for r in stub_server["requests"] if r["path"] == "/audio_query"
    )
    assert query_body["text"] == "これはテストです。"

    synth_body = next(
        r["body"] for r in stub_server["requests"] if r["path"].startswith("/synthesis")
    )
    # Controls must survive the round trip or the request was decorative.
    assert synth_body["speedScale"] == pytest.approx(1.15)
    assert synth_body["postPhonemeLength"] == pytest.approx(0.3)


def test_aivisspeech_emphasis_marks_matching_moras():
    provider = get("aivisspeech")
    phrases = [{"accent": 1, "moras": [{"text": "ほ", "pitch": 5.0}, {"text": "ん", "pitch": 5.0}]}]
    type(provider)._apply_emphasis(phrases, ["ほ"])
    assert phrases[0]["moras"][0]["pitch"] > 5.0
    assert phrases[0]["moras"][1]["pitch"] == 5.0


# --------------------------------------------------------- openai compatible
def test_openai_tts_missing_key_is_not_ready(monkeypatch):
    for name in ("HVW_TTS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    provider = get("openai_compatible_tts")
    result = provider.probe()
    assert result.state is ProbeState.MISSING_CREDENTIALS
    assert "HVW_TTS_API_KEY" in result.reason
    assert provider.descriptor().available is CapabilityFlag.NO


def test_openai_tts_never_exposes_the_raw_key(monkeypatch):
    """The masked form must appear; the real key must not."""
    secret = "sk-supersecretvalue1234567890"
    monkeypatch.setenv("HVW_TTS_API_KEY", secret)
    provider = get("openai_compatible_tts")
    result = provider.probe()
    descriptor = provider.descriptor()

    assert provider.masked_key == "sk-****890"
    blob = json.dumps({"probe": result.model_dump(), "desc": descriptor.model_dump()})
    assert secret not in blob
    assert "sk-****890" in blob


def test_openai_tts_maps_request_and_writes_audio(stub_server, monkeypatch):
    stub_server["routes"]["/audio/speech"] = (200, _tiny_wav(), "audio/wav")
    monkeypatch.setenv("HVW_TTS_API_KEY", "sk-test-key-abcdef123456")
    monkeypatch.setenv("HVW_TTS_BASE_URL", stub_server["base_url"])
    monkeypatch.setenv("HVW_TTS_MODEL", "tts-1-hd")


    stub_server["requests"].clear()
    import tempfile
    from pathlib import Path

    provider = get("openai_compatible_tts")
    output = Path(tempfile.mkdtemp()) / "line.wav"
    provider.synthesize(
        TTSRequest(
            text="Hello there.",
            language="en-US",
            voice="nova",
            speed=1.1,
            output_path=str(output),
            output_format=AudioFormat.WAV,
        )
    )
    call = stub_server["requests"][-1]
    assert call["path"] == "/audio/speech"
    assert call["body"]["model"] == "tts-1-hd"
    assert call["body"]["voice"] == "nova"
    assert call["body"]["speed"] == pytest.approx(1.1)
    assert call["headers"].get("Authorization") == "Bearer sk-test-key-abcdef123456"


def test_openai_tts_reports_unsupported_fields(stub_server, monkeypatch):
    stub_server["routes"]["/audio/speech"] = (200, _tiny_wav(), "audio/wav")
    monkeypatch.setenv("HVW_TTS_API_KEY", "sk-test-key-abcdef123456")
    monkeypatch.setenv("HVW_TTS_BASE_URL", stub_server["base_url"])


    import tempfile
    from pathlib import Path

    provider = get("openai_compatible_tts")
    result = provider.synthesize_rich(
        TTSRequest(
            text="Hello.",
            emotion="excited",
            pitch=2.0,
            output_path=str(Path(tempfile.mkdtemp()) / "x.wav"),
        )
    )
    # The engine ignores emotion and pitch. Saying so is the contract.
    assert "emotion" in result.unsupported_fields
    assert "pitch" in result.unsupported_fields
    assert result.realtime_factor is not None


def test_openai_tts_rate_limit_maps_to_timeout(stub_server, monkeypatch):
    stub_server["routes"]["/audio/speech"] = (429, "slow down", "text/plain")
    monkeypatch.setenv("HVW_TTS_API_KEY", "sk-test-key-abcdef123456")
    monkeypatch.setenv("HVW_TTS_BASE_URL", stub_server["base_url"])

    from html_video_workflow.providers.base import ProviderTimeout

    import tempfile
    from pathlib import Path

    provider = get("openai_compatible_tts")
    with pytest.raises(ProviderTimeout):
        provider.synthesize(
            TTSRequest(text="Hi.", output_path=str(Path(tempfile.mkdtemp()) / "y.wav"))
        )


# ------------------------------------------------------------ neural sidecar
def test_neural_sidecar_not_installed_without_url(monkeypatch):
    monkeypatch.delenv("HVW_NEURAL_TTS_URL", raising=False)
    provider = get("neural_sidecar")
    result = provider.probe()
    assert result.state is ProbeState.NOT_INSTALLED
    descriptor = provider.descriptor()
    assert descriptor.installed is CapabilityFlag.NO
    assert descriptor.available is CapabilityFlag.NO
    assert descriptor.requires_gpu is GPURequirement.OPTIONAL
    assert descriptor.quality_tier is QualityTier.STUDIO


def test_neural_sidecar_probes_health_and_voices(stub_server, monkeypatch):
    stub_server["routes"]["/health"] = (
        200, json.dumps({"status": "ok", "gpu": "RTX 4090"}), "application/json"
    )
    stub_server["routes"]["/v1/voices"] = (
        200,
        json.dumps([{"id": "v1", "name": "Narrator", "language": "zh-CN"}]),
        "application/json",
    )
    monkeypatch.setenv("HVW_NEURAL_TTS_URL", stub_server["base_url"])
    monkeypatch.setenv("HVW_NEURAL_TTS_ENGINE", "fish-speech")

    provider = get("neural_sidecar")
    result = provider.probe()
    assert result.state is ProbeState.READY
    assert result.evidence["voices"] == 1
    assert provider.descriptor().voice_count == 1


def test_neural_sidecar_unhealthy_status_is_unavailable(stub_server, monkeypatch):
    stub_server["routes"]["/health"] = (
        200, json.dumps({"status": "loading"}), "application/json"
    )
    monkeypatch.setenv("HVW_NEURAL_TTS_URL", stub_server["base_url"])

    result = get("neural_sidecar").probe()
    assert result.state is ProbeState.UNAVAILABLE
    assert "loading" in result.reason


def test_neural_sidecar_synthesis_forwards_controls(stub_server, monkeypatch):
    stub_server["routes"]["/v1/tts"] = (200, _tiny_wav(), "audio/wav")
    monkeypatch.setenv("HVW_NEURAL_TTS_URL", stub_server["base_url"])
    monkeypatch.setenv("HVW_NEURAL_TTS_ENGINE", "cosyvoice")


    import tempfile
    from pathlib import Path

    stub_server["requests"].clear()
    provider = get("neural_sidecar")
    output = Path(tempfile.mkdtemp()) / "n.wav"
    response = provider.synthesize(
        TTSRequest(
            text="本地优先。",
            language="zh-CN",
            voice="narrator",
            emotion="calm",
            speed=0.95,
            seed=42,
            emphasis=["本地"],
            output_path=str(output),
        )
    )
    assert response.audio_path
    body = stub_server["requests"][-1]["body"]
    assert body["emotion"] == "calm"
    assert body["seed"] == 42
    assert body["emphasis"] == ["本地"]
    assert body["language"] == "zh-CN"


def test_neural_sidecar_gateway_timeout_is_a_timeout(stub_server, monkeypatch):
    stub_server["routes"]["/v1/tts"] = (504, "gateway timeout", "text/plain")
    monkeypatch.setenv("HVW_NEURAL_TTS_URL", stub_server["base_url"])

    from html_video_workflow.providers.base import ProviderTimeout

    import tempfile
    from pathlib import Path

    with pytest.raises(ProviderTimeout):
        get("neural_sidecar").synthesize(
            TTSRequest(text="Hi.", output_path=str(Path(tempfile.mkdtemp()) / "z.wav"))
        )


# ------------------------------------------------------------------- request
def test_request_clamps_insane_controls():
    """A planner bug must not become a provider 400."""
    request = TTSRequest(text="x", speed=99.0, pitch=-999.0)
    assert request.speed == 4.0
    assert request.pitch == -24.0


def test_requested_features_reflects_only_what_was_asked():
    assert TTSRequest(text="x").requested_features() == set()
    asked = TTSRequest(text="x", emotion="calm", seed=1, emphasis=["a"])
    assert asked.requested_features() == {"emotion", "seed", "emphasis"}


def test_capability_flag_only_yes_is_truthy():
    assert CapabilityFlag.YES.truthy
    assert not CapabilityFlag.NO.truthy
    assert not CapabilityFlag.UNKNOWN.truthy, "unknown must never read as support"


# ------------------------------------------------- resolved language capability
class _NarrowingProvider:
    """A provider that declares more than this machine can actually say.

    Modelled on SAPI, which declares ``zh-CN`` on every Windows install because
    the Speech API supports it — while the voices installed on a given box may
    be en-US only.
    """

    from html_video_workflow.providers.base import ProviderSpec as _Spec

    spec = _Spec(
        id="narrowing", type=ProviderType.TTS, name="Narrowing", vendor="test",
        version="1.0.0", local=True, implementation="inprocess",
        languages=["zh-CN", "en-US"],
    )

    def probe(self):
        from html_video_workflow.providers.base import ProbeResult

        return ProbeResult(state=ProbeState.READY, reason="stub")

    def descriptor(self):
        from html_video_workflow.providers.tts.contract import (
            CapabilityFlag,
            TTSProviderDescriptor,
        )

        return TTSProviderDescriptor(
            id="narrowing", name="Narrowing", vendor="test", version="1.0.0",
            implementation="inprocess", available=CapabilityFlag.YES, local=True,
            languages=["en-US"],  # what the probe actually found
            probed=True, reason="stub",
        )


def _narrowing_capability():
    from html_video_workflow.providers.base import TTSProvider

    class _Provider(_NarrowingProvider, TTSProvider):  # type: ignore[misc]
        def synthesize(self, request):  # pragma: no cover - not exercised
            raise NotImplementedError

    return _Provider().capabilities()


def test_a_probe_narrows_a_declared_language():
    """The declared claim is what the engine *can* do; the probe is the truth.

    Regression: the router read the declaration, so a Chinese request was routed
    to an engine whose only installed voice was English. Wrong-language speech is
    worse than an obvious placeholder, because it sounds like a working product
    rather than a missing voice.
    """
    capability = _narrowing_capability()
    assert capability.languages == ["en-US"], (
        "a declared language with no installed voice must not survive the probe")


def test_a_contradicted_claim_is_corrected_not_emptied():
    """An empty intersection must not read as `undeclared`.

    ``_language_match`` treats an empty language list as "support undeclared",
    which the router lets through — so reporting an empty list here would
    *remove* the language check instead of tightening it, the exact opposite of
    what the probe learned.
    """
    from html_video_workflow.pipeline.router import _language_match

    capability = _narrowing_capability()
    match, note = _language_match(capability.languages, "zh-CN")
    assert match == "none", f"zh-CN should be refused, got {match} ({note})"


# ------------------------------------------------------------ speech vs a tone
def _energy_spread(path) -> float:
    """Normalised spread of short-window energy. A steady sine scores ~0.

    Duration cannot separate speech from a placeholder — both providers scale
    their output to the estimated narration length. Structure can: a tone holds
    a constant amplitude, speech does not.
    """
    import math
    import struct
    import wave

    with wave.open(str(path), "rb") as handle:
        channels, rate, width = (handle.getnchannels(), handle.getframerate(),
                                 handle.getsampwidth())
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise AssertionError(f"expected 16-bit samples, got {width * 8}-bit")

    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    if channels > 1:
        samples = samples[::channels]
    size = max(1, rate * 25 // 1000)  # 25 ms windows
    rms = [math.sqrt(sum(s * s for s in samples[i:i + size]) / size)
           for i in range(0, len(samples) - size, size)]
    mean = sum(rms) / len(rms)
    if mean <= 0:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in rms) / len(rms)) / mean


def test_the_placeholder_is_measurably_a_tone():
    """The control. Without this, the test below proves nothing about *speech*.

    `mock_tts` is the only provider that must sound like a tone, so it is the
    calibration point: whatever threshold is used to call SAPI "speech" has to
    reject this.
    """
    from html_video_workflow.providers.base import NarrationSpec, TTSRequest

    target = Path(tempfile.mkdtemp(prefix="hvw-tone-")) / "mock.wav"
    get("mock_tts").synthesize(TTSRequest(
        narration=NarrationSpec(text="为什么本地 AI 很重要", language="zh-CN"),
        output_path=str(target)))

    assert _energy_spread(target) < 0.1, "the placeholder stopped sounding like a tone"


@pytest.mark.skipif(
    not get("sapi").capabilities().available,
    reason="no SAPI on this platform, so there is no real voice to compare")
def test_a_real_voice_produces_speech_not_a_tone():
    """A ready voice must actually speak.

    Regression guard for the whole point of the routing fix: if `sapi` were ever
    routed to while producing a tone — or if its installed-voice list were wrong
    — the pipeline would still report success, because a tone of the right length
    passes audio QC. Only the waveform tells the truth.
    """
    from html_video_workflow.providers.base import NarrationSpec, TTSRequest

    target = Path(tempfile.mkdtemp(prefix="hvw-speech-")) / "sapi.wav"
    get("sapi").synthesize(TTSRequest(
        narration=NarrationSpec(text="为什么本地 AI 很重要", language="zh-CN"),
        output_path=str(target)))

    spread = _energy_spread(target)
    assert spread > 0.4, (
        f"sapi output has the energy profile of a steady tone (spread {spread:.3f}); "
        f"a real voice scores above 1.0")
