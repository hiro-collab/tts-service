from __future__ import annotations

import platform

from tts_service.core.types import AudioArtifact


class LocalSpeakerPlayer:
    def play(self, audio: AudioArtifact) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("LocalSpeakerPlayer currently supports Windows WAV playback only")

        import winsound

        winsound.PlaySound(str(audio.path), winsound.SND_FILENAME)
