from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from tts_service.core.dedupe import DedupeStore
from tts_service.core.types import TtsPhase, TtsRequest, TtsResult, TtsState, utc_now_iso
from tts_service.ports.player import Player
from tts_service.ports.status_sink import StatusSink
from tts_service.ports.synthesizer import Synthesizer


class TtsPipeline:
    def __init__(
        self,
        synthesizer: Synthesizer,
        player: Player,
        status_sink: StatusSink | None = None,
        dedupe_store: DedupeStore | None = None,
        cleanup_transient_audio: bool = True,
    ) -> None:
        self.synthesizer = synthesizer
        self.player = player
        self.status_sink = status_sink
        self.dedupe_store = dedupe_store
        self.cleanup_transient_audio = cleanup_transient_audio

    def speak(self, request: TtsRequest) -> TtsResult:
        started_at = utc_now_iso()
        if self.dedupe_store and self.dedupe_store.has_seen(request):
            self._write_state(TtsState.from_request(TtsPhase.SKIPPED, request))
            return TtsResult(
                request=request,
                phase=TtsPhase.SKIPPED,
                started_at=started_at,
                completed_at=utc_now_iso(),
            )

        audio_path: Path | None = None
        audio = None
        try:
            if not request.text.strip():
                raise ValueError("TTS request text is empty")

            self._write_state(TtsState.from_request(TtsPhase.SPEAKING, request))
            audio = self.synthesizer.synthesize(request)
            audio_path = audio.path
            self.player.play(audio)
            if self.dedupe_store:
                self.dedupe_store.mark_seen(request)
            completed_at = utc_now_iso()
            self._write_state(TtsState.from_request(TtsPhase.COMPLETED, request))
            return TtsResult(
                request=request,
                phase=TtsPhase.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                audio=audio,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            completed_at = utc_now_iso()
            self._write_state(TtsState.from_request(TtsPhase.ERROR, request, error=error))
            return TtsResult(
                request=request,
                phase=TtsPhase.ERROR,
                started_at=started_at,
                completed_at=completed_at,
                audio=audio,
                error=error,
            )
        finally:
            if (
                self.cleanup_transient_audio
                and audio is not None
                and audio.transient
                and audio_path is not None
            ):
                with suppress(OSError):
                    audio_path.unlink()

    def _write_state(self, state: TtsState) -> None:
        if self.status_sink is None:
            return
        self.status_sink.write_state(state)
        self.status_sink.write_event(state)
