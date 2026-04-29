from __future__ import annotations

from array import array
from contextlib import suppress
from pathlib import Path
import shutil
import sys
import uuid
import wave

from tts_service.core.types import AudioArtifact
from tts_service.ports.player import Player
from tts_service.ports.volume import VolumeProvider


class VolumeControlledPlayer:
    """Applies app-level WAV gain before delegating playback."""

    def __init__(self, inner: Player, volume_provider: VolumeProvider, work_dir: Path) -> None:
        self.inner = inner
        self.volume_provider = volume_provider
        self.work_dir = work_dir

    def play(self, audio: AudioArtifact) -> None:
        volume = self.volume_provider.get_volume()
        if volume == 1.0:
            self.inner.play(audio)
            return
        if audio.mime_type != "audio/wav":
            raise RuntimeError(f"app volume control only supports audio/wav, got {audio.mime_type}")

        self.work_dir.mkdir(parents=True, exist_ok=True)
        adjusted_path = self.work_dir / f"{audio.path.stem}.volume-{uuid.uuid4().hex}.wav"
        try:
            scale_wav_volume(audio.path, adjusted_path, volume)
            adjusted = AudioArtifact(
                path=adjusted_path,
                mime_type=audio.mime_type,
                transient=True,
                metadata={**dict(audio.metadata), "app_volume": volume},
            )
            self.inner.play(adjusted)
        finally:
            with suppress(OSError):
                adjusted_path.unlink()

    def stop(self) -> None:
        stop = getattr(self.inner, "stop", None)
        if callable(stop):
            stop()

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()


def scale_wav_volume(input_path: Path, output_path: Path, volume: float) -> None:
    if not 0.0 <= volume <= 1.0:
        raise ValueError("app volume must be between 0.0 and 1.0")
    if volume == 1.0:
        if input_path.resolve() != output_path.resolve():
            shutil.copy2(input_path, output_path)
        return

    with wave.open(str(input_path), "rb") as source:
        params = source.getparams()
        if params.comptype != "NONE":
            raise RuntimeError(f"unsupported WAV compression: {params.comptype}")
        frames = source.readframes(params.nframes)

    scaled = _scale_pcm_frames(frames, params.sampwidth, volume)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as target:
        target.setparams(params)
        target.writeframes(scaled)


def _scale_pcm_frames(frames: bytes, sample_width: int, volume: float) -> bytes:
    if sample_width == 1:
        return bytes(_clamp_int(round((sample - 128) * volume + 128), 0, 255) for sample in frames)
    if sample_width == 2:
        return _scale_array_samples(frames, "h", -32768, 32767, volume)
    if sample_width == 3:
        return _scale_24_bit_samples(frames, volume)
    if sample_width == 4:
        return _scale_array_samples(frames, "i", -2147483648, 2147483647, volume)
    raise RuntimeError(f"unsupported WAV sample width: {sample_width}")


def _scale_array_samples(
    frames: bytes,
    typecode: str,
    minimum: int,
    maximum: int,
    volume: float,
) -> bytes:
    samples = array(typecode)
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        samples[index] = _clamp_int(round(sample * volume), minimum, maximum)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _scale_24_bit_samples(frames: bytes, volume: float) -> bytes:
    output = bytearray()
    minimum = -8388608
    maximum = 8388607
    for index in range(0, len(frames), 3):
        sample_bytes = frames[index : index + 3]
        if len(sample_bytes) < 3:
            break
        raw = int.from_bytes(sample_bytes, byteorder="little", signed=False)
        if raw & 0x800000:
            raw -= 0x1000000
        scaled = _clamp_int(round(raw * volume), minimum, maximum)
        if scaled < 0:
            scaled += 0x1000000
        output.extend(scaled.to_bytes(3, byteorder="little", signed=False))
    return bytes(output)


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))
