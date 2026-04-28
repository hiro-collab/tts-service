from __future__ import annotations

import json
import unittest
from pathlib import Path

from tts_service.core.dedupe import InMemoryDedupeStore, JsonDedupeStore
from tts_service.core.types import TtsRequest
from tests.helpers import workspace_temp_dir


class DedupeTests(unittest.TestCase):
    def test_message_id_is_primary_identity(self) -> None:
        first = TtsRequest(text="hello", message_id="msg-1")
        second = TtsRequest(text="different text", message_id="msg-1")

        self.assertEqual(first.identity_key, second.identity_key)

    def test_conversation_and_text_hash_identity_has_no_plain_text(self) -> None:
        request = TtsRequest(text="secret response", conversation_id="conv-1")

        self.assertIn("conversation:conv-1:text:", request.identity_key)
        self.assertNotIn("secret response", request.identity_key)

    def test_in_memory_store_tracks_seen_requests(self) -> None:
        store = InMemoryDedupeStore()
        request = TtsRequest(text="hello")

        self.assertFalse(store.has_seen(request))
        store.mark_seen(request)
        self.assertTrue(store.has_seen(request))

    def test_json_store_persists_seen_keys(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = Path(temp_dir) / "seen.json"
            request = TtsRequest(text="hello", message_id="msg-1")
            store = JsonDedupeStore(path)
            store.mark_seen(request)

            reloaded = JsonDedupeStore(path)
            self.assertTrue(reloaded.has_seen(request))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)


if __name__ == "__main__":
    unittest.main()
