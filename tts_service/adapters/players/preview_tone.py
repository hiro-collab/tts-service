from __future__ import annotations

from array import array
from contextlib import suppress
import math
from pathlib import Path
import sys
import uuid
import wave

from tts_service.adapters.players.local_speaker import LocalSpeakerPlayer
from tts_service.adapters.players.volume_control import VolumeControlledPlayer
from tts_service.adapters.volume.json_volume_store import StaticVolumeProvider, validate_app_volume
from tts_service.core.types import AudioArtifact


def play_preview_tone(
    volume: float,
    work_dir: Path,
    frequency_hz: float = 880.0,
    duration_seconds: float = 0.2,
) -> None:
    volume = validate_app_volume(volume)
    work_dir.mkdir(parents=True, exist_ok=True)
    tone_path = work_dir / f"preview-{uuid.uuid4().hex}.wav"
    try:
        write_preview_tone(tone_path, frequency_hz=frequency_hz, duration_seconds=duration_seconds)
        player = VolumeControlledPlayer(
            LocalSpeakerPlayer(),
            StaticVolumeProvider(volume),
            work_dir / "adjusted",
        )
        player.play(AudioArtifact(path=tone_path, mime_type="audio/wav", transient=True))
    finally:
        with suppress(OSError):
            tone_path.unlink()


def write_preview_tone(
    path: Path,
    frequency_hz: float = 880.0,
    duration_seconds: float = 0.2,
    sample_rate: int = 44100,
) -> None:
    if duration_seconds <= 0:
        raise ValueError("preview duration must be positive")
    frame_count = max(1, int(sample_rate * duration_seconds))
    samples = array("h")
    for index in range(frame_count):
        t = index / sample_rate
        envelope = max(0.0, 1.0 - (index / frame_count))
        sample = int(26000 * envelope * math.sin(2.0 * math.pi * frequency_hz * t))
        samples.append(sample)
    if sys.byteorder != "little":
        samples.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(samples.tobytes())
