from __future__ import annotations

import json
from pathlib import Path
from urllib import parse, request as urlrequest

from tts_service.core.types import AudioArtifact, TtsRequest


class VoicevoxSynthesizer:
    """VOICEVOX Engine HTTP adapter.

    Requires a running VOICEVOX Engine, usually at http://127.0.0.1:50021.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:50021",
        speaker: int = 1,
        output_dir: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.speaker = speaker
        self.output_dir = output_dir or Path(".cache/tts_service/audio")
        self.timeout = timeout

    def synthesize(self, request: TtsRequest) -> AudioArtifact:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        query_url = (
            f"{self.endpoint}/audio_query?"
            + parse.urlencode({"text": request.text, "speaker": self.speaker})
        )
        query_req = urlrequest.Request(query_url, method="POST")
        with urlrequest.urlopen(query_req, timeout=self.timeout) as response:
            audio_query = response.read()

        synth_url = f"{self.endpoint}/synthesis?" + parse.urlencode({"speaker": self.speaker})
        synth_req = urlrequest.Request(
            synth_url,
            data=audio_query,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlrequest.urlopen(synth_req, timeout=self.timeout) as response:
            wav_bytes = response.read()

        wav_path = self.output_dir / f"{request.request_id}.wav"
        wav_path.write_bytes(wav_bytes)
        return AudioArtifact(
            path=wav_path,
            mime_type="audio/wav",
            transient=True,
            metadata={"engine": "voicevox", "speaker": self.speaker},
        )


def pretty_audio_query(audio_query: bytes) -> dict:
    return json.loads(audio_query.decode("utf-8"))
