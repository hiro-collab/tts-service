from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
from typing import Any

from tts_service.adapters.players.file_output import FileOutputPlayer
from tts_service.adapters.players.local_speaker import LocalSpeakerPlayer
from tts_service.adapters.players.noop import NoopPlayer
from tts_service.adapters.players.volume_control import VolumeControlledPlayer
from tts_service.adapters.sources.http_source import HttpTtsRequestSource
from tts_service.adapters.sources.sword_status_store import SwordStatusStoreSource
from tts_service.adapters.status.json_status_store import JsonStatusStore
from tts_service.adapters.synthesizers.noop import NoopSynthesizer
from tts_service.adapters.synthesizers.windows_sapi import (
    WindowsSapiSynthesizer,
    check_windows_sapi_silent,
    list_windows_sapi_voices,
)
from tts_service.adapters.volume.json_volume_store import (
    JsonVolumeProvider,
    validate_app_volume,
    volume_from_payload,
    write_app_volume,
)
from tts_service.core.dedupe import JsonDedupeStore
from tts_service.core.pipeline import TtsPipeline
from tts_service.core.runtime import (
    RuntimeStatusWriter,
    ShutdownController,
    command_line_for_module,
    install_signal_handlers,
)
from tts_service.core.types import TtsState, utc_now_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch sword-voice-agent status files and speak new Dify responses.")
    parser.add_argument("--source", choices=("status-file", "http"), default="status-file")
    parser.add_argument("--status-dir", type=Path, help="Directory containing latest_dify_response.json.")
    parser.add_argument("--output-status-dir", type=Path, default=Path(".cache/tts_service"))
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--http-queue-size", type=int, default=100)
    parser.add_argument("--http-chunk-max-chars", type=int, default=80)
    parser.add_argument("--shutdown-token", help="Token required for POST /shutdown. Required for non-loopback HTTP binds.")
    parser.add_argument("--runtime-status-file", type=Path, help="Write PID and shutdown metadata to this JSON file.")
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
    parser.add_argument("--app-volume", type=_app_volume_arg, default=1.0, help="App volume from 0.0 to 1.0.")
    parser.add_argument("--app-volume-file", type=Path, help="JSON file read before playback for app volume.")
    return parser


def main(argv: list[str] | None = None) -> int:
    command_line = command_line_for_module("tts_service.apps.watch_sword_response", argv)
    args = build_parser().parse_args(argv)
    if args.list_voices:
        return _list_voices(json_output=args.json)

    if args.source == "status-file" and args.status_dir is None:
        message = "--status-dir is required with --source status-file"
        if args.health_json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 2

    volume_provider = _build_volume_provider(args)
    shutdown = ShutdownController()
    pipeline_holder: dict[str, TtsPipeline | None] = {"pipeline": None}
    try:
        source = _build_source(args, volume_provider, shutdown, lambda: _current_phase(pipeline_holder))
    except Exception as exc:
        if args.health_json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        print(f"failed to start source: {exc}", file=sys.stderr)
        return 2
    source_target = _source_target(source)
    status_store: JsonStatusStore | None = None
    context: dict[str, Any] | None = None
    pipeline: TtsPipeline | None = None
    runtime_writer = RuntimeStatusWriter(args.runtime_status_file)
    runtime_started = False
    watcher_started = False
    try:
        if args.health_json:
            health = _build_health(args, source_target)
            print(json.dumps(health, ensure_ascii=False))
            return 0 if health["ok"] else 1

        if args.dry_run:
            return _dry_run(args, source_target)

        if args.source == "status-file" and args.status_dir is not None and not args.status_dir.exists():
            print(f"status directory does not exist: {args.status_dir}", file=sys.stderr)
            return 2

        effective_player = _effective_player_name(args.engine, args.player)
        _print_startup(args, source, source_target, effective_player)
        install_signal_handlers(shutdown)

        status_store = JsonStatusStore(args.output_status_dir)
        context = _state_context(args, source_target, effective_player, volume_provider, service="running")
        idle_state = TtsState.idle(**_materialized_state_context(context))
        status_store.write_state(idle_state)
        status_store.write_event(idle_state)
        runtime_writer.write_running(
            module="tts_service",
            started_at=utc_now_iso(),
            host=_runtime_host(source),
            port=_runtime_port(source),
            health_url=_runtime_health_url(source),
            shutdown_url=_runtime_shutdown_url(source),
            shutdown_command=None if isinstance(source, HttpTtsRequestSource) else "SIGINT or SIGTERM",
            command_line=command_line,
        )
        runtime_started = True
        watcher_started = True
        volume_tracker = VolumeStatusTracker(_app_volume_file(args), volume_provider.get_volume())

        dedupe_store = JsonDedupeStore(args.output_status_dir / "seen_requests.json")
        synthesizer = _build_synthesizer(args)
        player = _build_player(args, effective_player, volume_provider)
        pipeline = TtsPipeline(
            synthesizer=synthesizer,
            player=player,
            status_sink=status_store,
            dedupe_store=dedupe_store,
            state_context=context,
        )
        pipeline_holder["pipeline"] = pipeline
        shutdown.add_callback(lambda _reason: pipeline.stop())

        try:
            while not shutdown.is_requested():
                request = source.next_request()
                if request is not None:
                    result = pipeline.speak(request)
                    if not result.ok:
                        print(result.error, file=sys.stderr)
                else:
                    _write_idle_if_volume_changed(volume_tracker, volume_provider, status_store, context)
                if args.once:
                    break
                if args.source == "status-file":
                    shutdown.wait(args.poll_interval)
        except KeyboardInterrupt:
            shutdown.request("keyboard_interrupt")
            return 130
        return _shutdown_exit_code(shutdown)
    finally:
        if pipeline is not None:
            pipeline.close()
        _close_source(source)
        if status_store is not None and context is not None and shutdown.is_requested():
            stopped_context = dict(context)
            stopped_context["service"] = "stopped"
            stopped_state = TtsState.idle(**_materialized_state_context(stopped_context))
            status_store.write_state(stopped_state)
            status_store.write_event(stopped_state)
        if runtime_started:
            runtime_writer.write_stopped()
        if watcher_started and (shutdown.is_requested() or not args.once):
            print("tts_service watcher stopped", flush=True)


def _build_source(
    args: argparse.Namespace,
    volume_provider: JsonVolumeProvider,
    shutdown: ShutdownController,
    phase_getter: Any,
):
    if args.source == "http":
        return HttpTtsRequestSource(
            host=args.http_host,
            port=args.http_port,
            queue_size=args.http_queue_size,
            max_chunk_chars=args.http_chunk_max_chars,
            volume_getter=lambda: _volume_payload(args, volume_provider),
            volume_setter=lambda payload: _set_volume_from_http(args, volume_provider, payload),
            phase_getter=phase_getter,
            shutdown_callback=lambda: shutdown.request("http_shutdown"),
            shutdown_token=args.shutdown_token,
        )
    assert args.status_dir is not None
    return SwordStatusStoreSource(args.status_dir)


def _source_target(source: Any) -> str:
    if isinstance(source, HttpTtsRequestSource):
        return source.endpoint
    if isinstance(source, SwordStatusStoreSource):
        return str(source.latest_path)
    return str(source)


def _close_source(source: Any) -> None:
    close = getattr(source, "close", None)
    if callable(close):
        close()


def _current_phase(pipeline_holder: dict[str, TtsPipeline | None]) -> str:
    pipeline = pipeline_holder.get("pipeline")
    if pipeline is None:
        return "idle"
    return pipeline.phase.value


def _runtime_host(source: Any) -> str | None:
    if isinstance(source, HttpTtsRequestSource):
        return source.host
    return None


def _runtime_port(source: Any) -> int | None:
    if isinstance(source, HttpTtsRequestSource):
        return source.port
    return None


def _runtime_health_url(source: Any) -> str | None:
    if isinstance(source, HttpTtsRequestSource):
        return source.health_endpoint
    return None


def _runtime_shutdown_url(source: Any) -> str | None:
    if isinstance(source, HttpTtsRequestSource):
        return source.shutdown_endpoint
    return None


def _shutdown_exit_code(shutdown: ShutdownController) -> int:
    if shutdown.reason in {"keyboard_interrupt", "signal:2"}:
        return 130
    if shutdown.reason and shutdown.reason.startswith("signal:"):
        try:
            return 128 + int(shutdown.reason.partition(":")[2])
        except ValueError:
            return 0
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


def _build_player(args: argparse.Namespace, effective_player: str, volume_provider: JsonVolumeProvider):
    if effective_player == "noop":
        return NoopPlayer()
    if effective_player == "file":
        base_player = FileOutputPlayer(args.output_audio_dir)
    else:
        base_player = LocalSpeakerPlayer()
    return VolumeControlledPlayer(base_player, volume_provider, args.output_status_dir / "volume")


def _effective_player_name(engine: str, player: str) -> str:
    if engine == "noop":
        return "noop"
    return player


def _state_context(
    args: argparse.Namespace,
    source_target: str,
    effective_player: str,
    volume_provider: JsonVolumeProvider,
    service: str,
) -> dict[str, Any]:
    return {
        "service": service,
        "watching": source_target,
        "engine": args.engine,
        "player": effective_player,
        "voice_name": args.voice_name or None,
        "poll_interval": args.poll_interval if args.source == "status-file" else None,
        "app_volume": volume_provider.get_volume,
        "app_volume_file": str(_app_volume_file(args)),
        "volume": args.volume,
        "rate": args.rate,
    }


def _materialized_state_context(context: dict[str, Any]) -> dict[str, Any]:
    materialized = dict(context)
    app_volume = materialized.get("app_volume")
    if callable(app_volume):
        materialized["app_volume"] = app_volume()
    return materialized


class VolumeStatusTracker:
    def __init__(self, path: Path, volume: float) -> None:
        self.path = path
        self.signature = _file_signature(path)
        self.volume = volume

    def refresh_changed(self, volume: float) -> bool:
        signature = _file_signature(self.path)
        changed = signature != self.signature or volume != self.volume
        self.signature = signature
        self.volume = volume
        return changed


def _write_idle_if_volume_changed(
    tracker: VolumeStatusTracker,
    volume_provider: JsonVolumeProvider,
    status_store: JsonStatusStore,
    context: dict[str, Any],
) -> None:
    volume = volume_provider.get_volume()
    if not tracker.refresh_changed(volume):
        return
    state = TtsState.idle(**_materialized_state_context(context))
    status_store.write_state(state)
    status_store.write_event(state)


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _print_startup(args: argparse.Namespace, source: Any, source_target: str, effective_player: str) -> None:
    print("tts_service watcher starting", flush=True)
    print(f"  source: {args.source}", flush=True)
    print(f"  watching: {source_target}", flush=True)
    if isinstance(source, HttpTtsRequestSource):
        print(f"  health_endpoint: {source.health_endpoint}", flush=True)
        print(f"  chunk_endpoint: {source.chunk_endpoint}", flush=True)
        print(f"  volume_endpoint: {source.volume_endpoint}", flush=True)
        print(f"  shutdown_endpoint: {source.shutdown_endpoint}", flush=True)
    print(f"  output_status_dir: {args.output_status_dir}", flush=True)
    print(f"  engine: {args.engine}", flush=True)
    print(f"  player: {effective_player}", flush=True)
    print(f"  voice_name: {args.voice_name or '(default)'}", flush=True)
    print(f"  volume: {args.volume}", flush=True)
    print(f"  rate: {args.rate}", flush=True)
    print(f"  app_volume: {_build_volume_provider(args).get_volume()}", flush=True)
    print(f"  app_volume_file: {_app_volume_file(args)}", flush=True)
    print(f"  poll_interval: {args.poll_interval if args.source == 'status-file' else '(event queue)'}", flush=True)


def _dry_run(args: argparse.Namespace, source_target: str) -> int:
    effective_player = _effective_player_name(args.engine, args.player)
    _print_startup(args, None, source_target, effective_player)
    checks = _path_checks(args, source_target)
    for key, value in checks.items():
        print(f"  {key}: {value}", flush=True)
    return 0 if checks["input_available"] and checks["output_status_dir_usable"] else 2


def _build_health(args: argparse.Namespace, source_target: str) -> dict[str, Any]:
    effective_player = _effective_player_name(args.engine, args.player)
    checks = _path_checks(args, source_target)
    volume_provider = _build_volume_provider(args)
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
        checks["input_available"]
        and checks["output_status_dir_usable"]
        and player_ok
        and bool(engine_health["ok"])
    )
    return {
        "ok": ok,
        "service": "tts_service",
        "mode": "health",
        "watching": source_target,
        "output_status_dir": str(args.output_status_dir),
        "source": args.source,
        "poll_interval": args.poll_interval if args.source == "status-file" else None,
        "volume": args.volume,
        "rate": args.rate,
        "app_volume": volume_provider.get_volume(),
        "app_volume_file": str(_app_volume_file(args)),
        "engine": engine_health,
        "player": {"name": effective_player, "ok": player_ok},
        "paths": checks,
    }


def _path_checks(args: argparse.Namespace, source_target: str) -> dict[str, Any]:
    output_status_dir_usable = _can_create_or_use_dir(args.output_status_dir)
    app_volume_file = _app_volume_file(args)
    volume_provider = _build_volume_provider(args)
    if args.source == "http":
        return {
            "source": "http",
            "input_available": True,
            "endpoint": source_target,
            "status_dir": None,
            "status_dir_readable": None,
            "latest_path": None,
            "latest_exists": None,
            "output_status_dir": str(args.output_status_dir),
            "output_status_dir_usable": output_status_dir_usable,
            "volume": args.volume,
            "rate": args.rate,
            "app_volume": volume_provider.get_volume(),
            "app_volume_file": str(app_volume_file),
            "app_volume_file_exists": app_volume_file.exists(),
        }

    latest_path = Path(source_target)
    return {
        "source": "status-file",
        "input_available": _is_readable_dir(args.status_dir),
        "status_dir": str(args.status_dir),
        "status_dir_readable": _is_readable_dir(args.status_dir),
        "latest_path": source_target,
        "latest_exists": latest_path.exists(),
        "output_status_dir": str(args.output_status_dir),
        "output_status_dir_usable": output_status_dir_usable,
        "volume": args.volume,
        "rate": args.rate,
        "app_volume": volume_provider.get_volume(),
        "app_volume_file": str(app_volume_file),
        "app_volume_file_exists": app_volume_file.exists(),
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


def _build_volume_provider(args: argparse.Namespace) -> JsonVolumeProvider:
    return JsonVolumeProvider(_app_volume_file(args), default_volume=args.app_volume)


def _volume_payload(args: argparse.Namespace, volume_provider: JsonVolumeProvider) -> dict[str, Any]:
    return {
        "ok": True,
        "app_volume": volume_provider.get_volume(),
        "app_volume_file": str(_app_volume_file(args)),
    }


def _set_volume_from_http(
    args: argparse.Namespace,
    volume_provider: JsonVolumeProvider,
    payload: Any,
) -> dict[str, Any]:
    volume = volume_from_payload(payload, default=volume_provider.default_volume)
    write_app_volume(_app_volume_file(args), volume)
    return _volume_payload(args, volume_provider)


def _app_volume_file(args: argparse.Namespace) -> Path:
    return args.app_volume_file or args.output_status_dir / "app_volume.json"


def _app_volume_arg(value: str) -> float:
    try:
        return validate_app_volume(float(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
