from __future__ import annotations

import json
import unittest
from pathlib import Path

from tts_service.adapters.status.json_status_store import JsonStatusStore
from tts_service.core.types import TtsPhase, TtsRequest, TtsState
from tests.helpers import workspace_temp_dir


class JsonStatusStoreTests(unittest.TestCase):
    def test_status_store_does_not_write_plain_text(self) -> None:
        with workspace_temp_dir() as temp_dir:
            store = JsonStatusStore(Path(temp_dir))
            request = TtsRequest(
                text="sensitive answer",
                message_id="msg-1",
                conversation_id="conv-1",
                source="sword_status_store",
                metadata={"turn_id": "turn-1"},
            )

            state = TtsState.from_request(TtsPhase.SPEAKING, request).with_context(
                service="running",
                watching="C:/status/latest_dify_response.json",
                engine="noop",
                player="noop",
                poll_interval=1.0,
            )
            store.write_state(state)
            store.write_event(TtsState.from_request(TtsPhase.SPEAKING, request))

            latest = json.loads((Path(temp_dir) / "latest_tts_state.json").read_text(encoding="utf-8"))
            events = (Path(temp_dir) / "events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("sensitive answer", json.dumps(latest, ensure_ascii=False))
            self.assertNotIn("sensitive answer", events)
            self.assertEqual(latest["phase"], "speaking")
            self.assertEqual(latest["service"], "running")
            self.assertEqual(latest["turn_id"], "turn-1")
            self.assertEqual(latest["engine"], "noop")
            self.assertEqual(latest["player"], "noop")


if __name__ == "__main__":
    unittest.main()
