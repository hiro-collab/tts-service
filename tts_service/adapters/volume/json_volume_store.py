from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tts_service.core.types import utc_now_iso


DEFAULT_APP_VOLUME = 1.0


class StaticVolumeProvider:
    def __init__(self, volume: float = DEFAULT_APP_VOLUME) -> None:
        self.volume = validate_app_volume(volume)

    def get_volume(self) -> float:
        return self.volume


class JsonVolumeProvider:
    def __init__(self, path: Path, default_volume: float = DEFAULT_APP_VOLUME) -> None:
        self.path = path
        self.default_volume = validate_app_volume(default_volume)

    def get_volume(self) -> float:
        if not self.path.exists():
            return self.default_volume
        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            return volume_from_payload(payload, default=self.default_volume)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self.default_volume


def write_app_volume(path: Path, volume: float) -> None:
    volume = validate_app_volume(volume)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "app_volume": volume,
        "updated_at": utc_now_iso(),
    }
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp_path.replace(path)


def volume_from_payload(payload: Any, default: float = DEFAULT_APP_VOLUME) -> float:
    if isinstance(payload, (int, float)):
        return validate_app_volume(float(payload))
    if not isinstance(payload, dict):
        return validate_app_volume(default)
    if payload.get("muted") is True:
        return 0.0
    for key in ("app_volume", "volume", "value"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return validate_app_volume(float(value))
    percent = payload.get("app_volume_percent")
    if isinstance(percent, (int, float)):
        return validate_app_volume(float(percent) / 100.0)
    return validate_app_volume(default)


def validate_app_volume(volume: float) -> float:
    if not 0.0 <= volume <= 1.0:
        raise ValueError("app volume must be between 0.0 and 1.0")
    return float(volume)
