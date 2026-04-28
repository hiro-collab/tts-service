from __future__ import annotations

import sys
from typing import TextIO

from tts_service.core.types import TtsRequest


class StdinSource:
    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdin

    def next_request(self) -> TtsRequest | None:
        line = self.stream.readline()
        if line == "":
            return None
        text = line.strip()
        if not text:
            return None
        return TtsRequest(text=text, source="stdin")
