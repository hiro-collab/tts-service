from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from pathlib import Path
import time
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def perf_counter_seconds() -> float:
    return time.perf_counter()


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
class TtsEvent:
    event: str
    wall_time: str = field(default_factory=utc_now_iso)
    monotonic_time: float = field(default_factory=perf_counter_seconds)
    request_id: str | None = None
    message_id: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    source: str | None = None
    text_hash: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        event: str,
        request: TtsRequest,
        *,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "TtsEvent":
        return cls(
            event=event,
            request_id=request.request_id,
            message_id=request.message_id,
            conversation_id=request.conversation_id,
            turn_id=_string_metadata(request.metadata, "turn_id"),
            source=request.source,
            text_hash=request.text_hash,
            error=error,
            metadata=dict(metadata or {}),
        )

    def with_context(
        self,
        service: str | None = None,
        watching: str | None = None,
        engine: str | None = None,
        player: str | None = None,
        voice_name: str | None = None,
        poll_interval: float | None = None,
        app_volume: float | None = None,
        app_volume_file: str | None = None,
        volume: int | None = None,
        rate: int | None = None,
    ) -> "TtsEvent":
        metadata = dict(self.metadata)
        for key, value in {
            "service": service,
            "watching": watching,
            "engine": engine,
            "player": player,
            "voice_name": voice_name,
            "poll_interval": poll_interval,
            "app_volume": app_volume,
            "app_volume_file": app_volume_file,
            "volume": volume,
            "rate": rate,
        }.items():
            if value is not None:
                metadata[key] = value
        return TtsEvent(
            event=self.event,
            wall_time=self.wall_time,
            monotonic_time=self.monotonic_time,
            request_id=self.request_id,
            message_id=self.message_id,
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            source=self.source,
            text_hash=self.text_hash,
            error=self.error,
            metadata=metadata,
        )

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "tts_event",
            "event": self.event,
            "wall_time": self.wall_time,
            "monotonic_time": self.monotonic_time,
            "perf_counter": self.monotonic_time,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "source": self.source,
            "text_hash": self.text_hash,
            "error": self.error,
        }
        context_keys = (
            "service",
            "watching",
            "engine",
            "player",
            "voice_name",
            "poll_interval",
            "app_volume",
            "app_volume_file",
            "volume",
            "rate",
        )
        for key in context_keys:
            payload[key] = self.metadata.get(key)
        payload.update(
            {
                key: value
                for key, value in self.metadata.items()
                if value is not None and key not in context_keys
            }
        )
        return payload


@dataclass(frozen=True)
class TtsState:
    phase: TtsPhase
    updated_at: str = field(default_factory=utc_now_iso)
    service: str | None = None
    request_id: str | None = None
    message_id: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    source: str | None = None
    watching: str | None = None
    engine: str | None = None
    player: str | None = None
    voice_name: str | None = None
    poll_interval: float | None = None
    app_volume: float | None = None
    app_volume_file: str | None = None
    volume: int | None = None
    rate: int | None = None
    text_hash: str | None = None
    error: str | None = None

    @classmethod
    def idle(
        cls,
        service: str | None = None,
        watching: str | None = None,
        engine: str | None = None,
        player: str | None = None,
        voice_name: str | None = None,
        poll_interval: float | None = None,
        app_volume: float | None = None,
        app_volume_file: str | None = None,
        volume: int | None = None,
        rate: int | None = None,
    ) -> "TtsState":
        return cls(
            phase=TtsPhase.IDLE,
            service=service,
            watching=watching,
            engine=engine,
            player=player,
            voice_name=voice_name,
            poll_interval=poll_interval,
            app_volume=app_volume,
            app_volume_file=app_volume_file,
            volume=volume,
            rate=rate,
        )

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
            turn_id=_string_metadata(request.metadata, "turn_id"),
            source=request.source,
            text_hash=request.text_hash,
            error=error,
        )

    def with_context(
        self,
        service: str | None = None,
        watching: str | None = None,
        engine: str | None = None,
        player: str | None = None,
        voice_name: str | None = None,
        poll_interval: float | None = None,
        app_volume: float | None = None,
        app_volume_file: str | None = None,
        volume: int | None = None,
        rate: int | None = None,
    ) -> "TtsState":
        return TtsState(
            phase=self.phase,
            updated_at=self.updated_at,
            service=service if service is not None else self.service,
            request_id=self.request_id,
            message_id=self.message_id,
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            source=self.source,
            watching=watching if watching is not None else self.watching,
            engine=engine if engine is not None else self.engine,
            player=player if player is not None else self.player,
            voice_name=voice_name if voice_name is not None else self.voice_name,
            poll_interval=poll_interval if poll_interval is not None else self.poll_interval,
            app_volume=app_volume if app_volume is not None else self.app_volume,
            app_volume_file=app_volume_file if app_volume_file is not None else self.app_volume_file,
            volume=volume if volume is not None else self.volume,
            rate=rate if rate is not None else self.rate,
            text_hash=self.text_hash,
            error=self.error,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "updated_at": self.updated_at,
            "service": self.service,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "source": self.source,
            "watching": self.watching,
            "engine": self.engine,
            "player": self.player,
            "voice_name": self.voice_name,
            "poll_interval": self.poll_interval,
            "app_volume": self.app_volume,
            "app_volume_file": self.app_volume_file,
            "volume": self.volume,
            "rate": self.rate,
            "text_hash": self.text_hash,
            "error": self.error,
        }


def _string_metadata(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None
