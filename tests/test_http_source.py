from __future__ import annotations

import json
import unittest
from urllib import request as urlrequest

from tts_service.adapters.sources.http_source import HttpTtsRequestSource
from tts_service.adapters.volume.json_volume_store import volume_from_payload


class HttpTtsRequestSourceTests(unittest.TestCase):
    def test_http_post_queues_tts_request(self) -> None:
        source = HttpTtsRequestSource(port=0, wait_timeout=0.01)
        try:
            response = _post_json(
                source.endpoint,
                {
                    "text": "hello",
                    "message_id": "msg-1",
                    "conversation_id": "conv-1",
                    "turn_id": "turn-1",
                },
            )

            request = source.next_request()

            self.assertTrue(response["ok"])
            self.assertIsNotNone(request)
            assert request is not None
            self.assertEqual(request.text, "hello")
            self.assertEqual(request.source, "http")
            self.assertEqual(request.message_id, "msg-1")
            self.assertEqual(request.metadata["turn_id"], "turn-1")
        finally:
            source.close()

    def test_chunk_endpoint_splits_and_flushes_streaming_text(self) -> None:
        source = HttpTtsRequestSource(port=0, wait_timeout=0.01, max_chunk_chars=20)
        try:
            first_response = _post_json(
                source.chunk_endpoint,
                {
                    "delta": "こんにちは。まだ",
                    "message_id": "msg-1",
                    "turn_id": "turn-1",
                },
            )
            first = source.next_request()

            second_response = _post_json(
                source.chunk_endpoint,
                {
                    "delta": "です",
                    "message_id": "msg-1",
                    "turn_id": "turn-1",
                    "final": True,
                },
            )
            second = source.next_request()

            self.assertEqual(first_response["accepted"], 1)
            self.assertIsNotNone(first)
            assert first is not None
            self.assertEqual(first.text, "こんにちは。")
            self.assertEqual(first.message_id, "msg-1:chunk:0")
            self.assertEqual(first.source, "http_chunk")
            self.assertEqual(first.metadata["chunk_index"], 0)
            self.assertFalse(first.metadata["chunk_final"])

            self.assertEqual(second_response["accepted"], 1)
            self.assertIsNotNone(second)
            assert second is not None
            self.assertEqual(second.text, "まだです")
            self.assertEqual(second.message_id, "msg-1:chunk:1")
            self.assertEqual(second.metadata["chunk_index"], 1)
            self.assertTrue(second.metadata["chunk_final"])
        finally:
            source.close()

    def test_volume_endpoint_gets_and_sets_app_volume(self) -> None:
        state = {"volume": 1.0}

        def get_volume() -> dict:
            return {"ok": True, "app_volume": state["volume"], "app_volume_file": "memory"}

        def set_volume(payload: dict) -> dict:
            state["volume"] = volume_from_payload(payload)
            return get_volume()

        source = HttpTtsRequestSource(
            port=0,
            wait_timeout=0.01,
            volume_getter=get_volume,
            volume_setter=set_volume,
        )
        try:
            first = _get_json(source.volume_endpoint)
            second = _post_json(source.volume_endpoint, {"app_volume": 0.3})
            third = _get_json(source.volume_endpoint)

            self.assertEqual(first["app_volume"], 1.0)
            self.assertEqual(second["app_volume"], 0.3)
            self.assertEqual(third["app_volume"], 0.3)
        finally:
            source.close()


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urlrequest.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlrequest.urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urlrequest.urlopen(url, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
