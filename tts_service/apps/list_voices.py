from __future__ import annotations

import argparse
import json
import sys

from tts_service.adapters.synthesizers.windows_sapi import list_windows_sapi_voices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List Windows SAPI voices.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        voices = list_windows_sapi_voices()
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "voices": []}, ensure_ascii=False))
        else:
            print(f"failed to list Windows SAPI voices: {exc}", file=sys.stderr)
        return 1

    has_japanese = any(_is_japanese_voice(voice) for voice in voices)
    if args.json:
        print(json.dumps({"ok": True, "has_japanese": has_japanese, "voices": voices}, ensure_ascii=False))
        return 0

    if not voices:
        print("No Windows SAPI voices found.")
        return 0

    for voice in voices:
        suffix = " [Japanese]" if _is_japanese_voice(voice) else ""
        print(
            f"{voice.get('name', '(unknown)')} "
            f"({voice.get('culture', 'unknown')}, {voice.get('gender', 'unknown')}){suffix}"
        )
    print(f"Japanese voice available: {'yes' if has_japanese else 'no'}")
    return 0


def _is_japanese_voice(voice: dict) -> bool:
    culture = str(voice.get("culture", "")).lower()
    name = str(voice.get("name", "")).lower()
    return culture.startswith("ja") or "japanese" in name or "haruka" in name


if __name__ == "__main__":
    raise SystemExit(main())
