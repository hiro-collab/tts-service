from __future__ import annotations

from contextlib import suppress
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from tts_service.core.types import AudioArtifact, TtsRequest


POWERSHELL_SCRIPT = """
param(
    [Parameter(Mandatory=$true)][string]$TextPath,
    [Parameter(Mandatory=$true)][string]$OutPath,
    [string]$VoiceName = "",
    [int]$Rate = 0,
    [int]$Volume = 100
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($VoiceName -ne "") {
        $synth.SelectVoice($VoiceName)
    }
    $synth.Rate = $Rate
    $synth.Volume = $Volume
    $text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
    $synth.SetOutputToWaveFile($OutPath)
    $synth.Speak($text)
    $synth.SetOutputToNull()
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    $synth.Dispose()
}
"""

VOICE_LIST_SCRIPT = """
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @($synth.GetInstalledVoices() | ForEach-Object {
        $info = $_.VoiceInfo
        [PSCustomObject]@{
            name = $info.Name
            culture = $info.Culture.Name
            gender = $info.Gender.ToString()
            age = $info.Age.ToString()
            enabled = $_.Enabled
        }
    })
    [PSCustomObject]@{
        voices = $voices
    } | ConvertTo-Json -Depth 4 -Compress
}
finally {
    $synth.Dispose()
}
"""

SILENT_SPEAK_CHECK_SCRIPT = """
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SetOutputToNull()
    $synth.Speak("tts service health check")
    [PSCustomObject]@{
        ok = $true
    } | ConvertTo-Json -Compress
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    $synth.Dispose()
}
"""


class WindowsSapiSynthesizer:
    """Synthesizes WAV audio with Windows System.Speech via PowerShell."""

    def __init__(
        self,
        output_dir: Path | None = None,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
        powershell_executable: str | None = None,
    ) -> None:
        self.output_dir = output_dir or Path(".cache/tts_service/audio")
        self.voice_name = voice_name or ""
        self.rate = rate
        self.volume = volume
        self.powershell_executable = powershell_executable or _find_powershell()

    def synthesize(self, request: TtsRequest) -> AudioArtifact:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = self.output_dir / f"sapi_{uuid.uuid4().hex}"
        work_dir.mkdir(parents=False, exist_ok=False)
        text_path = work_dir / "input.txt"
        script_path = work_dir / "synthesize.ps1"
        wav_path = self.output_dir / f"{request.request_id}.wav"
        try:
            text_path.write_text(request.text, encoding="utf-8")
            script_path.write_text(POWERSHELL_SCRIPT, encoding="utf-8")
            completed = subprocess.run(
                [
                    self.powershell_executable,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    "-TextPath",
                    str(text_path),
                    "-OutPath",
                    str(wav_path),
                    "-VoiceName",
                    self.voice_name,
                    "-Rate",
                    str(self.rate),
                    "-Volume",
                    str(self.volume),
                ],
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                detail = _decode_process_output(completed.stderr or completed.stdout).strip()
                with suppress(OSError):
                    wav_path.unlink()
                raise RuntimeError(f"Windows SAPI synthesis failed: {detail}")
            if not wav_path.exists():
                raise RuntimeError("Windows SAPI synthesis did not create a WAV file")
            if wav_path.stat().st_size == 0:
                with suppress(OSError):
                    wav_path.unlink()
                raise RuntimeError(
                    "Windows SAPI created an empty WAV file. Ensure at least one "
                    "Windows speech voice is installed for the current user."
                )
            return AudioArtifact(
                path=wav_path,
                mime_type="audio/wav",
                transient=True,
                metadata={"engine": "windows_sapi"},
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


def _find_powershell() -> str:
    for name in ("powershell", "pwsh"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("PowerShell executable was not found")


def list_windows_sapi_voices(powershell_executable: str | None = None) -> list[dict[str, Any]]:
    completed = _run_powershell_command(VOICE_LIST_SCRIPT, powershell_executable)
    if completed.returncode != 0:
        detail = _decode_process_output(completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Windows SAPI voice list failed: {detail}")

    raw = _decode_process_output(completed.stdout).strip()
    payload = json.loads(raw) if raw else {"voices": []}
    voices = payload.get("voices", [])
    if isinstance(voices, dict):
        voices = [voices]
    if not isinstance(voices, list):
        return []
    return [voice for voice in voices if isinstance(voice, dict)]


def check_windows_sapi_silent(powershell_executable: str | None = None) -> tuple[bool, str | None]:
    completed = _run_powershell_command(SILENT_SPEAK_CHECK_SCRIPT, powershell_executable)
    if completed.returncode == 0:
        return True, None
    detail = _decode_process_output(completed.stderr or completed.stdout).strip()
    return False, detail or "Windows SAPI silent speak check failed"


def _run_powershell_command(
    script: str,
    powershell_executable: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    executable = powershell_executable or _find_powershell()
    return subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        check=False,
    )


def _decode_process_output(output: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp932"):
        try:
            text = output.decode(encoding)
            if encoding == "utf-8" and "\x00" in text:
                continue
            return text.lstrip("\ufeff")
        except UnicodeDecodeError:
            continue
    return output.decode("utf-8", errors="replace")
