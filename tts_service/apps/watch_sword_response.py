from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

from tts_service.adapters.players.file_output import FileOutputPlayer
from tts_service.adapters.players.local_speaker import LocalSpeakerPlayer
from tts_service.adapters.players.noop import NoopPlayer
from tts_service.adapters.sources.sword_status_store import SwordStatusStoreSource
from tts_service.adapters.status.json_status_store import JsonStatusStore
from tts_service.adapters.synthesizers.noop import NoopSynthesizer
from tts_service.adapters.synthesizers.windows_sapi import (
    WindowsSapiSynthesizer,
    check_windows_sapi_silent,
    list_windows_sapi_voices,
)
from tts_service.core.dedupe import JsonDedupeStore
from tts_service.core.pipeline import TtsPipeline
from tts_service.core.types import TtsState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch sword-voice-agent status files and speak new Dify responses.")
    parser.add_argument("--status-dir", type=Path, help="Directory containing latest_dify_response.json.")
    parser.add_argument("--output-status-dir", type=Path, default=Path(".cache/tts_service"))
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true", help="Check once and exit. Useful for tests or scheduled runs.")
    parser.add_argument("--dry-run", action="store_true", help="Validate settings and paths, then exit.")
    parser.add_argument("--health-json", action="store_true", help="Print machine-readable startup health, then exit.")
    parser.add_argument("--list-voices", action="store_true", help="List Windows SAPI voices, then exit.")
    parser.add_argument("--json", action="store_true", help="Use JSON output with --list-voices.")
    parser.add_argument("--engine", choices=("windows-sapi", "noop"), default="windows-sapi")
    parser.add_argument("--player", choices=("speaker", "file", "noop"), default="speaker")
    parser.add_argument("--output-audio-dir", type=Path, default=Path(".cache/tts_service/audio_output"))
    parser.add_argument("--voice-name", default="")
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--volume", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_voices:
        return _list_voices(json_output=args.json)

    if args.status_dir is None:
        message = "--status-dir is required unless --list-voices is used"
        if args.health_json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 2

    source = SwordStatusStoreSource(args.status_dir)
    if args.health_json:
        health = _build_health(args, source.latest_path)
        print(json.dumps(health, ensure_ascii=False))
        return 0 if health["ok"] else 1

    if args.dry_run:
        return _dry_run(args, source.latest_path)

    if not args.status_dir.exists():
        print(f"status directory does not exist: {args.status_dir}", file=sys.stderr)
        return 2

    effective_player = _effective_player_name(args.engine, args.player)
    _print_startup(args, source.latest_path, effective_player)

    status_store = JsonStatusStore(args.output_status_dir)
    context = _state_context(args, source.latest_path, effective_player, service="running")
    idle_state = TtsState.idle(**context)
    status_store.write_state(idle_state)
    status_store.write_event(idle_state)

    dedupe_store = JsonDedupeStore(args.output_status_dir / "seen_requests.json")
    synthesizer = _build_synthesizer(args)
    player = _build_player(args, effective_player)
    pipeline = TtsPipeline(
        synthesizer=synthesizer,
        player=player,
        status_sink=status_store,
        dedupe_store=dedupe_store,
        state_context=context,
    )

    try:
        while True:
            request = source.next_request()
            if request is not None:
                result = pipeline.speak(request)
                if not result.ok:
                    print(result.error, file=sys.stderr)
            if args.once:
                break
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        stopped_context = _state_context(args, source.latest_path, effective_player, service="stopped")
        stopped_state = TtsState.idle(**stopped_context)
        status_store.write_state(stopped_state)
        status_store.write_event(stopped_state)
        print("tts_service watcher stopped", flush=True)
        return 130
    return 0


def _build_synthesizer(args: argparse.Namespace):
    if args.engine == "noop":
        return NoopSynthesizer()
    return WindowsSapiSynthesizer(
        output_dir=args.output_status_dir / "audio",
        voice_name=args.voice_name,
        rate=args.rate,
        volume=args.volume,
    )


def _build_player(args: argparse.Namespace, effective_player: str):
    if effective_player == "noop":
        return NoopPlayer()
    if effective_player == "file":
        return FileOutputPlayer(args.output_audio_dir)
    return LocalSpeakerPlayer()


def _effective_player_name(engine: str, player: str) -> str:
    if engine == "noop":
        return "noop"
    return player


def _state_context(
    args: argparse.Namespace,
    latest_path: Path,
    effective_player: str,
    service: str,
) -> dict[str, Any]:
    return {
        "service": service,
        "watching": str(latest_path),
        "engine": args.engine,
        "player": effective_player,
        "voice_name": args.voice_name or None,
        "poll_interval": args.poll_interval,
    }


def _print_startup(args: argparse.Namespace, latest_path: Path, effective_player: str) -> None:
    print("tts_service watcher starting", flush=True)
    print(f"  watching: {latest_path}", flush=True)
    print(f"  output_status_dir: {args.output_status_dir}", flush=True)
    print(f"  engine: {args.engine}", flush=True)
    print(f"  player: {effective_player}", flush=True)
    print(f"  voice_name: {args.voice_name or '(default)'}", flush=True)
    print(f"  poll_interval: {args.poll_interval}", flush=True)


def _dry_run(args: argparse.Namespace, latest_path: Path) -> int:
    effective_player = _effective_player_name(args.engine, args.player)
    _print_startup(args, latest_path, effective_player)
    checks = _path_checks(args, latest_path)
    for key, value in checks.items():
        print(f"  {key}: {value}", flush=True)
    return 0 if checks["status_dir_readable"] and checks["output_status_dir_usable"] else 2


def _build_health(args: argparse.Namespace, latest_path: Path) -> dict[str, Any]:
    effective_player = _effective_player_name(args.engine, args.player)
    checks = _path_checks(args, latest_path)
    player_ok = effective_player != "speaker" or platform.system() == "Windows"
    engine_health: dict[str, Any] = {"name": args.engine, "ok": True}

    if args.engine == "windows-sapi":
        voices: list[dict[str, Any]] = []
        voice_list_ok = False
        voice_list_error = None
        try:
            voices = list_windows_sapi_voices()
            voice_list_ok = True
        except Exception as exc:
            voice_list_error = str(exc)
        try:
            silent_ok, silent_error = check_windows_sapi_silent()
        except Exception as exc:
            silent_ok = False
            silent_error = str(exc)
        voice_name_available = _voice_name_available(args.voice_name, voices)
        engine_health = {
            "name": args.engine,
            "ok": voice_list_ok and silent_ok and voice_name_available,
            "voice_list_ok": voice_list_ok,
            "voice_list_error": voice_list_error,
            "silent_speak_ok": silent_ok,
            "silent_speak_error": silent_error,
            "voice_name_available": voice_name_available,
            "has_japanese": any(_is_japanese_voice(voice) for voice in voices),
            "voices": voices,
        }

    ok = (
        checks["status_dir_readable"]
        and checks["output_status_dir_usable"]
        and player_ok
        and bool(engine_health["ok"])
    )
    return {
        "ok": ok,
        "service": "tts_service",
        "mode": "health",
        "watching": str(latest_path),
        "output_status_dir": str(args.output_status_dir),
        "poll_interval": args.poll_interval,
        "engine": engine_health,
        "player": {"name": effective_player, "ok": player_ok},
        "paths": checks,
    }


def _path_checks(args: argparse.Namespace, latest_path: Path) -> dict[str, Any]:
    return {
        "status_dir": str(args.status_dir),
        "status_dir_readable": _is_readable_dir(args.status_dir),
        "latest_path": str(latest_path),
        "latest_exists": latest_path.exists(),
        "output_status_dir": str(args.output_status_dir),
        "output_status_dir_usable": _can_create_or_use_dir(args.output_status_dir),
    }


def _is_readable_dir(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_dir():
            return False
        list(path.iterdir())
        return True
    except OSError:
        return False


def _can_create_or_use_dir(path: Path) -> bool:
    if path.exists():
        return path.is_dir()
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return False
        current = parent
    return current.is_dir()


def _list_voices(json_output: bool) -> int:
    try:
        voices = list_windows_sapi_voices()
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc), "voices": []}, ensure_ascii=False))
        else:
            print(f"failed to list Windows SAPI voices: {exc}", file=sys.stderr)
        return 1

    has_japanese = any(_is_japanese_voice(voice) for voice in voices)
    if json_output:
        print(json.dumps({"ok": True, "has_japanese": has_japanese, "voices": voices}, ensure_ascii=False))
    else:
        for voice in voices:
            suffix = " [Japanese]" if _is_japanese_voice(voice) else ""
            print(
                f"{voice.get('name', '(unknown)')} "
                f"({voice.get('culture', 'unknown')}, {voice.get('gender', 'unknown')}){suffix}"
            )
        print(f"Japanese voice available: {'yes' if has_japanese else 'no'}")
    return 0


def _voice_name_available(voice_name: str, voices: list[dict[str, Any]]) -> bool:
    if not voice_name:
        return True
    return any(voice.get("name") == voice_name for voice in voices)


def _is_japanese_voice(voice: dict[str, Any]) -> bool:
    culture = str(voice.get("culture", "")).lower()
    name = str(voice.get("name", "")).lower()
    return culture.startswith("ja") or "japanese" in name or "haruka" in name


if __name__ == "__main__":
    raise SystemExit(main())
