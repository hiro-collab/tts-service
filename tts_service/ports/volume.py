from __future__ import annotations

from typing import Protocol


class VolumeProvider(Protocol):
    def get_volume(self) -> float:
        ...
