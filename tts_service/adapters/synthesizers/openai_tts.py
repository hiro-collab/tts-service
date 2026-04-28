from __future__ import annotations

from pathlib import Path

from tts_service.core.types import AudioArtifact, TtsRequest


class OpenAITtsSynthesizer:
    """Placeholder adapter boundary for a future OpenAI TTS implementation."""

    def __init__(self, output_dir: Path | None = None, model: str | None = None, voice: str | None = None) -> None:
        self.output_dir = output_dir
        self.model = model
        self.voice = voice

    def synthesize(self, request: TtsRequest) -> AudioArtifact:
        raise NotImplementedError(
            "OpenAI TTS is not implemented in the MVP. Keep API keys in the "
            "environment and add the SDK integration inside this adapter."
        )
