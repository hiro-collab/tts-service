from __future__ import annotations

import argparse
from pathlib import Path
import sys

from tts_service.adapters.players.file_output import FileOutputPlayer
from tts_service.adapters.players.local_speaker import LocalSpeakerPlayer
from tts_service.adapters.players.noop import NoopPlayer
from tts_service.adapters.status.json_status_store import JsonStatusStore
from tts_service.adapters.synthesizers.noop import NoopSynthesizer
from tts_service.adapters.synthesizers.windows_sapi import WindowsSapiSynthesizer
from tts_service.core.pipeline import TtsPipeline
from tts_service.core.types import TtsRequest, TtsState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Speak one text input through the configured TTS engine.")
    parser.add_argument("--text", help="Text to speak. Reads stdin when omitted.")
    parser.add_argument("--message-id", help="Optional message id for status and dedupe identity.")
    parser.add_argument("--conversation-id", help="Optional conversation id for status and dedupe identity.")
    parser.add_argument("--turn-id", help="Optional turn id for latency events and status.")
    parser.add_argument("--output-status-dir", type=Path, default=Path(".cache/tts_service"))
    parser.add_argument("--engine", choices=("windows-sapi", "noop"), default="windows-sapi")
    parser.add_argument("--player", choices=("speaker", "file", "noop"), default="speaker")
    parser.add_argument("--output-audio-dir", type=Path, default=Path(".cache/tts_service/audio_output"))
    parser.add_argument("--voice-name", default="")
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--volume", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = args.text if args.text is not None else sys.stdin.read()
    request = TtsRequest(
        text=text,
        message_id=args.message_id,
        conversation_id=args.conversation_id,
        source="cli",
        metadata={"turn_id": args.turn_id} if args.turn_id else {},
    )

    status_store = JsonStatusStore(args.output_status_dir)
    effective_player = "noop" if args.engine == "noop" else args.player
    idle_state = TtsState.idle(
        service="running",
        engine=args.engine,
        player=effective_player,
        voice_name=args.voice_name or None,
    )
    status_store.write_state(idle_state)
    status_store.write_event(idle_state)

    if args.engine == "noop":
        synthesizer = NoopSynthesizer()
    else:
        synthesizer = WindowsSapiSynthesizer(
            output_dir=args.output_status_dir / "audio",
            voice_name=args.voice_name,
            rate=args.rate,
            volume=args.volume,
        )
    if effective_player == "noop":
        player = NoopPlayer()
    elif effective_player == "file":
        player = FileOutputPlayer(args.output_audio_dir)
    else:
        player = LocalSpeakerPlayer()
    pipeline = TtsPipeline(
        synthesizer=synthesizer,
        player=player,
        status_sink=status_store,
        state_context={"service": "running", "engine": args.engine, "player": effective_player},
    )
    result = pipeline.speak(request)
    if not result.ok:
        print(result.error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
