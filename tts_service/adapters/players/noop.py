from __future__ import annotations

from tts_service.core.types import AudioArtifact


class NoopPlayer:
    """Test player that accepts audio artifacts without playing them."""

    def play(self, audio: AudioArtifact) -> None:
        return None
