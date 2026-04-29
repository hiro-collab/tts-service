from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from tts_service.adapters.players.preview_tone import play_preview_tone
from tts_service.adapters.volume.json_volume_store import validate_app_volume, write_app_volume


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Set tts_service app volume.")
    parser.add_argument("volume", type=_volume_arg, help="App volume from 0.0 to 1.0.")
    parser.add_argument("--output-status-dir", type=Path, default=Path(".cache/tts_service"))
    parser.add_argument("--app-volume-file", type=Path)
    parser.add_argument("--preview", dest="preview", action="store_true", default=True)
    parser.add_argument("--no-preview", dest="preview", action="store_false")
    parser.add_argument("--preview-frequency", type=float, default=880.0)
    parser.add_argument("--preview-duration", type=float, default=0.2)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.app_volume_file or args.output_status_dir / "app_volume.json"
    write_app_volume(path, args.volume)
    preview_error = None
    if args.preview:
        try:
            play_preview_tone(
                args.volume,
                args.output_status_dir / "volume_preview",
                frequency_hz=args.preview_frequency,
                duration_seconds=args.preview_duration,
            )
        except Exception as exc:
            preview_error = str(exc)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": preview_error is None,
                    "app_volume": args.volume,
                    "app_volume_file": str(path),
                    "preview": args.preview,
                    "preview_error": preview_error,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"app_volume={args.volume} written to {path}")
        if args.preview and preview_error is None:
            print("preview tone played")
        elif preview_error is not None:
            print(f"preview tone failed: {preview_error}", file=sys.stderr)
    return 0 if preview_error is None else 1


def _volume_arg(value: str) -> float:
    try:
        return validate_app_volume(float(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
