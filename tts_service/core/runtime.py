from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
import json
import os
import signal
import sys
import threading
from typing import Any

from tts_service.core.types import utc_now_iso


SENSITIVE_ARGS = {"--shutdown-token"}


class ShutdownController:
    """Coordinates cooperative shutdown across sources, players, and apps."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[str], None]] = []
        self.reason: str | None = None

    def request(self, reason: str = "shutdown") -> bool:
        callbacks: list[Callable[[str], None]] = []
        with self._lock:
            first_request = not self._event.is_set()
            if first_request:
                self.reason = reason
                self._event.set()
                callbacks = list(self._callbacks)
        for callback in callbacks:
            with suppress(Exception):
                callback(reason)
        return first_request

    def add_callback(self, callback: Callable[[str], None]) -> None:
        call_now = False
        reason = "shutdown"
        with self._lock:
            if self._event.is_set():
                call_now = True
                reason = self.reason or reason
            else:
                self._callbacks.append(callback)
        if call_now:
            with suppress(Exception):
                callback(reason)

    def is_requested(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class RuntimeStatusWriter:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._payload: dict[str, Any] | None = None

    def write_running(
        self,
        *,
        module: str,
        started_at: str,
        host: str | None,
        port: int | None,
        health_url: str | None,
        shutdown_url: str | None,
        shutdown_command: str | None,
        command_line: Sequence[str],
    ) -> None:
        payload = {
            "module": module,
            "state": "running",
            "pid": os.getpid(),
            "parent_pid": _parent_pid(),
            "started_at": started_at,
            "stopped_at": None,
            "host": host,
            "port": port,
            "health_url": health_url,
            "shutdown_url": shutdown_url,
            "shutdown_command": shutdown_command,
            "command_line": redact_command_line(command_line),
        }
        self._payload = payload
        self._write(payload)

    def write_stopped(self) -> None:
        if self._payload is None:
            return
        payload = dict(self._payload)
        payload["state"] = "stopped"
        payload["stopped_at"] = utc_now_iso()
        self._payload = payload
        self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)


def install_signal_handlers(controller: ShutdownController) -> None:
    def handle_signal(signum: int, _frame: Any) -> None:
        controller.request(f"signal:{signum}")

    for signum in _available_shutdown_signals():
        with suppress(ValueError):
            signal.signal(signum, handle_signal)


def command_line_for_module(module: str, argv: Sequence[str] | None) -> list[str]:
    if argv is None:
        return list(sys.argv)
    return [sys.executable, "-m", module, *argv]


def redact_command_line(command_line: Sequence[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for item in command_line:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        if item in SENSITIVE_ARGS:
            redacted.append(item)
            skip_next = True
            continue
        if any(item.startswith(f"{arg}=") for arg in SENSITIVE_ARGS):
            name, _, _value = item.partition("=")
            redacted.append(f"{name}=<redacted>")
            continue
        redacted.append(item)
    return redacted


def _available_shutdown_signals() -> list[int]:
    signals = [signal.SIGINT]
    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is not None:
        signals.append(sigterm)
    return signals


def _parent_pid() -> int | None:
    getppid = getattr(os, "getppid", None)
    if getppid is None:
        return None
    return getppid()
