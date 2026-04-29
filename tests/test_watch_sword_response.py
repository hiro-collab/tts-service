from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import threading
import time
import unittest
from pathlib import Path
from urllib import request as urlrequest

from tts_service.adapters.status.json_status_store import JsonStatusStore
from tts_service.adapters.volume.json_volume_store import JsonVolumeProvider, write_app_volume
from tts_service.apps.watch_sword_response import VolumeStatusTracker, _write_idle_if_volume_changed, main
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
            self.assertEqual(latest["volume"], 100)
            self.assertEqual(latest["rate"], 0)
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
            self.assertEqual(payload["volume"], 100)
            self.assertEqual(payload["rate"], 0)

    def test_volume_file_change_writes_idle_status(self) -> None:
        with workspace_temp_dir() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "tts"
            volume_file = output_dir / "app_volume.json"
            provider = JsonVolumeProvider(volume_file, default_volume=1.0)
            store = JsonStatusStore(output_dir)
            context = {
                "service": "running",
                "watching": "http://127.0.0.1:8765/api/tts",
                "engine": "noop",
                "player": "noop",
                "voice_name": None,
                "poll_interval": None,
                "app_volume": provider.get_volume,
                "app_volume_file": str(volume_file),
                "volume": 100,
                "rate": 0,
            }
            tracker = VolumeStatusTracker(volume_file, provider.get_volume())

            write_app_volume(volume_file, 0.4)
            _write_idle_if_volume_changed(tracker, provider, store, context)

            latest = json.loads((output_dir / "latest_tts_state.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["phase"], "idle")
            self.assertEqual(latest["app_volume"], 0.4)
            self.assertEqual(latest["app_volume_file"], str(volume_file))
            self.assertEqual(latest["volume"], 100)
            self.assertEqual(latest["rate"], 0)

    def test_http_source_writes_runtime_status_and_shutdown_stops_watcher(self) -> None:
        with workspace_temp_dir() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "tts"
            runtime_status_file = root / "runtime_status.json"
            exit_codes: list[int] = []

            def run_watcher() -> None:
                with redirect_stdout(io.StringIO()):
                    exit_codes.append(
                        main(
                            [
                                "--source",
                                "http",
                                "--http-port",
                                "0",
                                "--output-status-dir",
                                str(output_dir),
                                "--runtime-status-file",
                                str(runtime_status_file),
                                "--engine",
                                "noop",
                                "--player",
                                "noop",
                            ]
                        )
                    )

            thread = threading.Thread(target=run_watcher)
            thread.start()
            runtime = _wait_for_runtime_status(runtime_status_file, state="running")
            health = _get_json(runtime["health_url"])
            shutdown = _post_json(runtime["shutdown_url"], {})
            thread.join(timeout=3.0)

            stopped = json.loads(runtime_status_file.read_text(encoding="utf-8"))
            latest = json.loads((output_dir / "latest_tts_state.json").read_text(encoding="utf-8"))
            self.assertFalse(thread.is_alive())
            self.assertEqual(exit_codes, [0])
            self.assertEqual(runtime["module"], "tts_service")
            self.assertEqual(runtime["port"], health["port"])
            self.assertEqual(health["module"], "tts_service")
            self.assertEqual(health["phase"], "idle")
            self.assertTrue(shutdown["ok"])
            self.assertEqual(stopped["state"], "stopped")
            self.assertEqual(latest["service"], "stopped")

def _wait_for_runtime_status(path: Path, state: str) -> dict:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("state") == state:
                return payload
        time.sleep(0.05)
    raise AssertionError(f"runtime status file was not written with state={state}")


def _get_json(url: str) -> dict:
    with urlrequest.urlopen(url, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


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


if __name__ == "__main__":
    unittest.main()
