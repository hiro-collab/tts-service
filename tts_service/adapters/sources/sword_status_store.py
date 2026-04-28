from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tts_service.core.types import TtsRequest


TEXT_PATHS = (
    ("answer",),
    ("text",),
    ("content",),
    ("message",),
    ("response", "answer"),
    ("response", "text"),
    ("response", "content"),
    ("request", "text"),
    ("data", "answer"),
    ("data", "text"),
    ("dify_response", "answer"),
    ("dify_response", "text"),
    ("payload", "answer"),
    ("payload", "text"),
)

MESSAGE_ID_PATHS = (
    ("message_id",),
    ("id",),
    ("task_id",),
    ("response", "message_id"),
    ("data", "message_id"),
    ("dify_response", "message_id"),
    ("payload", "message_id"),
)

CONVERSATION_ID_PATHS = (
    ("conversation_id",),
    ("response", "conversation_id"),
    ("data", "conversation_id"),
    ("dify_response", "conversation_id"),
    ("payload", "conversation_id"),
)

TURN_ID_PATHS = (
    ("turn_id",),
    ("request", "context", "turn_id"),
    ("request", "turn_id"),
    ("response", "turn_id"),
    ("data", "turn_id"),
    ("payload", "turn_id"),
)


class SwordStatusStoreSource:
    def __init__(
        self,
        status_dir: Path,
        latest_filename: str = "latest_dify_response.json",
    ) -> None:
        self.status_dir = status_dir
        self.latest_path = status_dir / latest_filename
        self._last_signature: tuple[int, int] | None = None

    def next_request(self) -> TtsRequest | None:
        if not self.latest_path.exists():
            return None

        stat = self.latest_path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._last_signature:
            return None

        try:
            with self.latest_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (json.JSONDecodeError, OSError):
            return None

        request = request_from_sword_payload(payload)
        if request is None:
            self._last_signature = signature
            return None

        self._last_signature = signature
        return request


def request_from_sword_payload(payload: Any) -> TtsRequest | None:
    if isinstance(payload, dict) and payload.get("skipped") is True:
        return None

    text = _find_string(payload, TEXT_PATHS, recursive_keys=("answer", "text", "content"))
    if text is None or not text.strip():
        return None

    message_id = _find_string(payload, MESSAGE_ID_PATHS)
    conversation_id = _find_string(payload, CONVERSATION_ID_PATHS)
    turn_id = _find_string(payload, TURN_ID_PATHS)
    metadata = {"turn_id": turn_id} if turn_id else {}
    return TtsRequest(
        text=text,
        message_id=message_id,
        conversation_id=conversation_id,
        source="sword_status_store",
        metadata=metadata,
    )


def _find_string(
    payload: Any,
    paths: tuple[tuple[str, ...], ...],
    recursive_keys: tuple[str, ...] = (),
) -> str | None:
    for path in paths:
        value = _get_path(payload, path)
        if isinstance(value, str) and value.strip():
            return value
    if recursive_keys:
        return _find_string_recursive(payload, recursive_keys)
    return None


def _get_path(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _find_string_recursive(payload: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in payload.values():
            found = _find_string_recursive(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_string_recursive(item, keys)
            if found:
                return found
    return None
