from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from tts_service.adapters.players.file_output import FileOutputPlayer
from tts_service.adapters.players.local_speaker import LocalSpeakerPlayer
from tts_service.adapters.sources.sword_status_store import SwordStatusStoreSource
from tts_service.adapters.status.json_status_store import JsonStatusStore
from tts_service.adapters.synthesizers.windows_sapi import WindowsSapiSynthesizer
from tts_service.core.dedupe import JsonDedupeStore
from tts_service.core.pipeline import TtsPipeline
from tts_service.core.types import TtsState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch sword-voice-agent status files and speak new Dify responses.")
    parser.add_argument("--status-dir", type=Path, required=True, help="Directory containing latest_dify_response.json.")
    parser.add_argument("--output-status-dir", type=Path, default=Path(".cache/tts_service"))
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true", help="Check once and exit. Useful for tests or scheduled runs.")
    parser.add_argument("--engine", choices=("windows-sapi",), default="windows-sapi")
    parser.add_argument("--player", choices=("speaker", "file"), default="speaker")
    parser.add_argument("--output-audio-dir", type=Path, default=Path(".cache/tts_service/audio_output"))
    parser.add_argument("--voice-name", default="")
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--volume", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.status_dir.exists():
        print(f"status directory does not exist: {args.status_dir}", file=sys.stderr)
        return 2

    status_store = JsonStatusStore(args.output_status_dir)
    idle_state = TtsState.idle()
    status_store.write_state(idle_state)
    status_store.write_event(idle_state)

    source = SwordStatusStoreSource(args.status_dir)
    dedupe_store = JsonDedupeStore(args.output_status_dir / "seen_requests.json")
    synthesizer = WindowsSapiSynthesizer(
        output_dir=args.output_status_dir / "audio",
        voice_name=args.voice_name,
        rate=args.rate,
        volume=args.volume,
    )
    player = LocalSpeakerPlayer() if args.player == "speaker" else FileOutputPlayer(args.output_audio_dir)
    pipeline = TtsPipeline(
        synthesizer=synthesizer,
        player=player,
        status_sink=status_store,
        dedupe_store=dedupe_store,
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
        status_store.write_state(TtsState.idle())
        status_store.write_event(TtsState.idle())
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
