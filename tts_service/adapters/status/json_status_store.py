from __future__ import annotations

import json
from pathlib import Path

from tts_service.core.types import TtsState


class JsonStatusStore:
    def __init__(
        self,
        output_status_dir: Path,
        latest_filename: str = "latest_tts_state.json",
        events_filename: str = "events.jsonl",
    ) -> None:
        self.output_status_dir = output_status_dir
        self.latest_path = output_status_dir / latest_filename
        self.events_path = output_status_dir / events_filename

    def write_state(self, state: TtsState) -> None:
        self.output_status_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.latest_path.with_suffix(self.latest_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(state.to_public_dict(), file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.latest_path)

    def write_event(self, state: TtsState) -> None:
        self.output_status_dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as file:
            json.dump(state.to_public_dict(), file, ensure_ascii=False)
            file.write("\n")
