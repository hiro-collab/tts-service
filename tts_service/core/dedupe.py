from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Protocol

from tts_service.core.types import TtsRequest


class DedupeStore(Protocol):
    def has_seen(self, request: TtsRequest) -> bool:
        ...

    def mark_seen(self, request: TtsRequest) -> None:
        ...


class InMemoryDedupeStore:
    def __init__(self, initial_keys: Iterable[str] | None = None, max_entries: int = 1000) -> None:
        self.max_entries = max_entries
        self._keys: list[str] = []
        self._seen: set[str] = set()
        for key in initial_keys or []:
            self._add_key(key)

    def has_seen(self, request: TtsRequest) -> bool:
        return request.identity_key in self._seen

    def mark_seen(self, request: TtsRequest) -> None:
        self._add_key(request.identity_key)

    def snapshot(self) -> list[str]:
        return list(self._keys)

    def _add_key(self, key: str) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self._keys.append(key)
        while len(self._keys) > self.max_entries:
            removed = self._keys.pop(0)
            self._seen.discard(removed)


class JsonDedupeStore(InMemoryDedupeStore):
    def __init__(self, path: Path, max_entries: int = 1000) -> None:
        self.path = path
        initial_keys = self._load_keys(path)
        super().__init__(initial_keys=initial_keys, max_entries=max_entries)

    def mark_seen(self, request: TtsRequest) -> None:
        before = len(self._seen)
        super().mark_seen(request)
        if len(self._seen) != before:
            self._save()

    @staticmethod
    def _load_keys(path: Path) -> list[str]:
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return []
        keys = data.get("seen", [])
        if not isinstance(keys, list):
            return []
        return [key for key in keys if isinstance(key, str)]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"version": 1, "seen": self.snapshot()}
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)
