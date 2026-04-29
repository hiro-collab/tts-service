from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import unittest
from pathlib import Path

from tts_service.apps.watch_sword_response import main
from tests.helpers import workspace_temp_dir


class WatchSwordResponseTests(unittest.TestCase):
    def test_once_with_noop_engine_writes_turn_status(self) -> None:
        with workspace_temp_dir() as temp_dir:
            root = Path(temp_dir)
            status_dir = root / "sword"
            output_dir = root / "tts"
            status_dir.mkdir()
            (status_dir / "latest_dify_response.json").write_text(
                json.dumps(
                    {
                        "type": "dify_handoff_result",
                        "response": {
                            "text": "はい、今日はいい天気ですね。",
                            "conversation_id": "conv-1",
                            "message_id": "msg-1",
                        },
                        "turn_id": "turn-1",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--status-dir",
                        str(status_dir),
                        "--output-status-dir",
                        str(output_dir),
                        "--engine",
                        "noop",
                        "--player",
                        "noop",
                        "--app-volume",
                        "0.25",
                        "--once",
                    ]
                )

            latest = json.loads((output_dir / "latest_tts_state.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(latest["phase"], "completed")
            self.assertEqual(latest["service"], "running")
            self.assertEqual(latest["engine"], "noop")
            self.assertEqual(latest["player"], "noop")
            self.assertEqual(latest["app_volume"], 0.25)
            self.assertEqual(latest["turn_id"], "turn-1")
            self.assertEqual(latest["message_id"], "msg-1")

    def test_dry_run_validates_paths_without_writing_status(self) -> None:
        with workspace_temp_dir() as temp_dir:
            root = Path(temp_dir)
            status_dir = root / "sword"
            output_dir = root / "tts"
            status_dir.mkdir()

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--status-dir",
                        str(status_dir),
                        "--output-status-dir",
                        str(output_dir),
                        "--engine",
                        "noop",
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse((output_dir / "latest_tts_state.json").exists())

    def test_health_json_with_noop_engine(self) -> None:
        with workspace_temp_dir() as temp_dir:
            root = Path(temp_dir)
            status_dir = root / "sword"
            output_dir = root / "tts"
            status_dir.mkdir()
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "--status-dir",
                        str(status_dir),
                        "--output-status-dir",
                        str(output_dir),
                        "--engine",
                        "noop",
                        "--health-json",
                    ]
                )

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["engine"]["name"], "noop")
            self.assertEqual(payload["player"]["name"], "noop")
            self.assertEqual(payload["app_volume"], 1.0)


if __name__ == "__main__":
    unittest.main()
