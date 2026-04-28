from __future__ import annotations

import json
import unittest
from pathlib import Path

from tts_service.adapters.sources.sword_status_store import (
    SwordStatusStoreSource,
    request_from_sword_payload,
)
from tests.helpers import workspace_temp_dir


class SwordStatusStoreTests(unittest.TestCase):
    def test_extracts_request_from_flat_payload(self) -> None:
        request = request_from_sword_payload(
            {
                "message_id": "msg-1",
                "conversation_id": "conv-1",
                "answer": "こんにちは",
            }
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.text, "こんにちは")
        self.assertEqual(request.message_id, "msg-1")
        self.assertEqual(request.conversation_id, "conv-1")

    def test_extracts_request_from_nested_payload(self) -> None:
        request = request_from_sword_payload(
            {
                "payload": {
                    "message_id": "msg-2",
                    "conversation_id": "conv-2",
                    "answer": "nested answer",
                }
            }
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.text, "nested answer")
        self.assertEqual(request.message_id, "msg-2")

    def test_extracts_sword_voice_agent_handoff_payload(self) -> None:
        request = request_from_sword_payload(
            {
                "type": "dify_handoff_result",
                "request": {
                    "text": "今日はいい天気ですね",
                    "context": {
                        "turn_id": "turn-1",
                    },
                },
                "response": {
                    "type": "agent_response",
                    "text": "はい、今日はいい天気ですね。",
                    "conversation_id": "conv-1",
                    "message_id": "msg-1",
                },
                "skipped": False,
                "turn_id": "turn-1",
            }
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.text, "はい、今日はいい天気ですね。")
        self.assertEqual(request.message_id, "msg-1")
        self.assertEqual(request.conversation_id, "conv-1")
        self.assertEqual(request.metadata["turn_id"], "turn-1")

    def test_skipped_payload_is_not_read_aloud(self) -> None:
        request = request_from_sword_payload(
            {
                "response": {
                    "text": "do not speak",
                    "conversation_id": "conv-1",
                    "message_id": "msg-1",
                },
                "skipped": True,
                "turn_id": "turn-1",
            }
        )

        self.assertIsNone(request)

    def test_source_yields_only_after_file_change(self) -> None:
        with workspace_temp_dir() as temp_dir:
            status_dir = Path(temp_dir)
            latest = status_dir / "latest_dify_response.json"
            latest.write_text(
                json.dumps({"message_id": "msg-1", "answer": "first"}, ensure_ascii=False),
                encoding="utf-8",
            )
            source = SwordStatusStoreSource(status_dir)

            first = source.next_request()
            second = source.next_request()

            self.assertIsNotNone(first)
            self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
