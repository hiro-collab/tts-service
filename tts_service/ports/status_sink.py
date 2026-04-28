from __future__ import annotations

from typing import Protocol

from tts_service.core.types import TtsState


class StatusSink(Protocol):
    def write_state(self, state: TtsState) -> None:
        ...

    def write_event(self, state: TtsState) -> None:
        ...
