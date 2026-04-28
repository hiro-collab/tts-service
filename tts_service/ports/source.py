from __future__ import annotations

from typing import Protocol

from tts_service.core.types import TtsRequest


class TtsRequestSource(Protocol):
    def next_request(self) -> TtsRequest | None:
        ...
