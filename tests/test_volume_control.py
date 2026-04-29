from __future__ import annotations

from array import array
from pathlib import Path
import sys
import unittest
import wave

from tts_service.adapters.players.volume_control import VolumeControlledPlayer, scale_wav_volume
from tts_service.adapters.players.preview_tone import write_preview_tone
from tts_service.adapters.volume.json_volume_store import JsonVolumeProvider, StaticVolumeProvider, write_app_volume
from tts_service.core.types import AudioArtifact
from tests.helpers import workspace_temp_dir


class RecordingPlayer:
    def __init__(self) -> None:
        self.samples: list[int] = []

    def play(self, audio: AudioArtifact) -> None:
        self.samples = _read_samples(audio.path)


class VolumeControlTests(unittest.TestCase):
    def test_scale_wav_volume_halves_pcm_samples(self) -> None:
        with workspace_temp_dir() as temp_dir:
            input_path = Path(temp_dir) / "input.wav"
            output_path = Path(temp_dir) / "output.wav"
            _write_wav(input_path, [1000, -1000, 2000])

            scale_wav_volume(input_path, output_path, 0.5)

            self.assertEqual(_read_samples(output_path), [500, -500, 1000])

    def test_json_volume_provider_reads_written_volume(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = Path(temp_dir) / "app_volume.json"
            provider = JsonVolumeProvider(path, default_volume=0.75)

            self.assertEqual(provider.get_volume(), 0.75)
            write_app_volume(path, 0.25)
            self.assertEqual(provider.get_volume(), 0.25)

    def test_volume_controlled_player_adjusts_audio_before_playback(self) -> None:
        with workspace_temp_dir() as temp_dir:
            input_path = Path(temp_dir) / "input.wav"
            _write_wav(input_path, [1200])
            inner = RecordingPlayer()
            player = VolumeControlledPlayer(
                inner,
                StaticVolumeProvider(0.25),
                Path(temp_dir) / "volume",
            )

            player.play(AudioArtifact(path=input_path, mime_type="audio/wav", transient=False))

            self.assertEqual(inner.samples, [300])

    def test_preview_tone_writes_wav(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = Path(temp_dir) / "preview.wav"

            write_preview_tone(path, duration_seconds=0.05)

            self.assertTrue(path.exists())
            with wave.open(str(path), "rb") as file:
                self.assertEqual(file.getnchannels(), 1)
                self.assertEqual(file.getsampwidth(), 2)
                self.assertGreater(file.getnframes(), 0)


def _write_wav(path: Path, samples: list[int]) -> None:
    data = array("h", samples)
    if sys.byteorder != "little":
        data.byteswap()
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(data.tobytes())


def _read_samples(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as file:
        frames = file.readframes(file.getnframes())
    data = array("h")
    data.frombytes(frames)
    if sys.byteorder != "little":
        data.byteswap()
    return list(data)


if __name__ == "__main__":
    unittest.main()
