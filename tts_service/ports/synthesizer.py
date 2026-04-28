from __future__ import annotations

from typing import Protocol

from tts_service.core.types import AudioArtifact, TtsRequest


class Synthesizer(Protocol):
    def synthesize(self, request: TtsRequest) -> AudioArtifact:
        ...
