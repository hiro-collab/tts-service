from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from pathlib import Path
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_text(text: str) -> str:
    return " ".join(text.strip().split())


def hash_text(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


class TtsPhase(str, Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TtsRequest:
    text: str
    message_id: str | None = None
    conversation_id: str | None = None
    source: str = "manual"
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def text_hash(self) -> str:
        return hash_text(self.text)

    @property
    def identity_key(self) -> str:
        if self.message_id:
            return f"message:{self.message_id}"
        if self.conversation_id:
            return f"conversation:{self.conversation_id}:text:{self.text_hash}"
        return f"text:{self.text_hash}"

    @property
    def request_id(self) -> str:
        return hashlib.sha256(self.identity_key.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class AudioArtifact:
    path: Path
    mime_type: str = "audio/wav"
    transient: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TtsResult:
    request: TtsRequest
    phase: TtsPhase
    started_at: str
    completed_at: str
    audio: AudioArtifact | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.phase in {TtsPhase.COMPLETED, TtsPhase.SKIPPED}


@dataclass(frozen=True)
class TtsState:
    phase: TtsPhase
    updated_at: str = field(default_factory=utc_now_iso)
    request_id: str | None = None
    message_id: str | None = None
    conversation_id: str | None = None
    source: str | None = None
    text_hash: str | None = None
    error: str | None = None

    @classmethod
    def idle(cls) -> "TtsState":
        return cls(phase=TtsPhase.IDLE)

    @classmethod
    def from_request(
        cls,
        phase: TtsPhase,
        request: TtsRequest,
        error: str | None = None,
    ) -> "TtsState":
        return cls(
            phase=phase,
            request_id=request.request_id,
            message_id=request.message_id,
            conversation_id=request.conversation_id,
            source=request.source,
            text_hash=request.text_hash,
            error=error,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "updated_at": self.updated_at,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "source": self.source,
            "text_hash": self.text_hash,
            "error": self.error,
        }
