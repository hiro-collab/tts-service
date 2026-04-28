from __future__ import annotations

import unittest
from pathlib import Path

from tts_service.core.dedupe import InMemoryDedupeStore
from tts_service.core.pipeline import TtsPipeline
from tts_service.core.types import AudioArtifact, TtsPhase, TtsRequest, TtsState
from tests.helpers import workspace_temp_dir


class FakeSynthesizer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0

    def synthesize(self, request: TtsRequest) -> AudioArtifact:
        self.calls += 1
        self.path.write_bytes(b"RIFF")
        return AudioArtifact(path=self.path, transient=False)


class FakePlayer:
    def __init__(self) -> None:
        self.calls = 0

    def play(self, audio: AudioArtifact) -> None:
        self.calls += 1


class FakeStatusSink:
    def __init__(self) -> None:
        self.states: list[TtsState] = []

    def write_state(self, state: TtsState) -> None:
        self.states.append(state)

    def write_event(self, state: TtsState) -> None:
        pass


class PipelineTests(unittest.TestCase):
    def test_successful_speak_updates_status_and_dedupe(self) -> None:
        with workspace_temp_dir() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            synth = FakeSynthesizer(audio_path)
            player = FakePlayer()
            status = FakeStatusSink()
            dedupe = InMemoryDedupeStore()
            pipeline = TtsPipeline(synth, player, status_sink=status, dedupe_store=dedupe)
            request = TtsRequest(text="hello", message_id="msg-1")

            result = pipeline.speak(request)

            self.assertEqual(result.phase, TtsPhase.COMPLETED)
            self.assertTrue(dedupe.has_seen(request))
            self.assertEqual([state.phase for state in status.states], [TtsPhase.SPEAKING, TtsPhase.COMPLETED])
            self.assertEqual(synth.calls, 1)
            self.assertEqual(player.calls, 1)

    def test_duplicate_request_is_skipped(self) -> None:
        with workspace_temp_dir() as temp_dir:
            request = TtsRequest(text="hello", message_id="msg-1")
            dedupe = InMemoryDedupeStore()
            dedupe.mark_seen(request)
            synth = FakeSynthesizer(Path(temp_dir) / "audio.wav")
            player = FakePlayer()
            status = FakeStatusSink()
            pipeline = TtsPipeline(synth, player, status_sink=status, dedupe_store=dedupe)

            result = pipeline.speak(request)

            self.assertEqual(result.phase, TtsPhase.SKIPPED)
            self.assertEqual(synth.calls, 0)
            self.assertEqual(player.calls, 0)
            self.assertEqual(status.states[-1].phase, TtsPhase.SKIPPED)


if __name__ == "__main__":
    unittest.main()
