from __future__ import annotations

import json
import os
import threading
import unittest
from urllib.error import HTTPError
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

    def test_health_endpoint_reports_runtime_details(self) -> None:
        source = HttpTtsRequestSource(port=0, wait_timeout=0.01, phase_getter=lambda: "speaking")
        try:
            health = _get_json(source.health_endpoint)

            self.assertTrue(health["ok"])
            self.assertEqual(health["module"], "tts_service")
            self.assertEqual(health["pid"], os.getpid())
            self.assertEqual(health["host"], source.host)
            self.assertEqual(health["port"], source.port)
            self.assertEqual(health["volume_endpoint"], source.volume_endpoint)
            self.assertEqual(health["queued"], 0)
            self.assertEqual(health["phase"], "speaking")
        finally:
            source.close()

    def test_shutdown_endpoint_requests_graceful_shutdown(self) -> None:
        shutdown_called = threading.Event()
        source = HttpTtsRequestSource(
            port=0,
            wait_timeout=0.01,
            shutdown_callback=shutdown_called.set,
        )
        try:
            response = _post_json(source.shutdown_endpoint, {})

            self.assertTrue(response["ok"])
            self.assertTrue(response["shutting_down"])
            self.assertTrue(shutdown_called.wait(timeout=1.0))
            self.assertTrue(source.shutdown_requested)
        finally:
            source.close()

    def test_shutdown_token_is_required_for_non_loopback_bind(self) -> None:
        with self.assertRaises(ValueError):
            HttpTtsRequestSource(host="0.0.0.0", port=0, wait_timeout=0.01)

    def test_shutdown_endpoint_accepts_bearer_token(self) -> None:
        source = HttpTtsRequestSource(port=0, wait_timeout=0.01, shutdown_token="secret")
        try:
            with self.assertRaises(HTTPError) as context:
                _post_json(source.shutdown_endpoint, {})
            self.assertEqual(context.exception.code, 401)

            response = _post_json(
                source.shutdown_endpoint,
                {},
                headers={"Authorization": "Bearer secret"},
            )
            self.assertTrue(response["ok"])
        finally:
            source.close()


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urlrequest.Request(
        url,
        data=data,
        method="POST",
        headers=request_headers,
    )
    with urlrequest.urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urlrequest.urlopen(url, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
