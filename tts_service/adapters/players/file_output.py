from __future__ import annotations

import shutil
from pathlib import Path

from tts_service.core.types import AudioArtifact


class FileOutputPlayer:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.last_output_path: Path | None = None

    def play(self, audio: AudioArtifact) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / audio.path.name
        if audio.path.resolve() != target.resolve():
            shutil.copy2(audio.path, target)
        self.last_output_path = target
