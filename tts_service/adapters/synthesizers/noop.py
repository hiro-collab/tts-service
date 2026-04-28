from __future__ import annotations

from pathlib import Path

from tts_service.core.types import AudioArtifact, TtsRequest


class NoopSynthesizer:
    """Test synthesizer that performs no synthesis and creates no audio."""

    def synthesize(self, request: TtsRequest) -> AudioArtifact:
        return AudioArtifact(
            path=Path("noop-audio"),
            mime_type="application/octet-stream",
            transient=False,
            metadata={"engine": "noop"},
        )
