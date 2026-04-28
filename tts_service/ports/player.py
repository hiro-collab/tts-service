from __future__ import annotations

from typing import Protocol

from tts_service.core.types import AudioArtifact


class Player(Protocol):
    def play(self, audio: AudioArtifact) -> None:
        ...
