from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import queue
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from tts_service.adapters.sources.sword_status_store import request_from_sword_payload
from tts_service.core.chunking import StreamingTextChunker
from tts_service.core.types import TtsRequest


CHUNK_TEXT_PATHS = (
    ("delta",),
    ("text",),
    ("answer",),
    ("data", "delta"),
    ("data", "text"),
    ("data", "answer"),
    ("payload", "delta"),
    ("payload", "text"),
    ("payload", "answer"),
)

TURN_ID_PATHS = (
    ("turn_id",),
    ("data", "turn_id"),
    ("payload", "turn_id"),
    ("request", "context", "turn_id"),
)

MESSAGE_ID_PATHS = (
    ("message_id",),
    ("id",),
    ("data", "message_id"),
    ("payload", "message_id"),
    ("response", "message_id"),
)

CONVERSATION_ID_PATHS = (
    ("conversation_id",),
    ("data", "conversation_id"),
    ("payload", "conversation_id"),
    ("response", "conversation_id"),
)


class HttpTtsRequestSource:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        request_path: str = "/api/tts",
        chunk_path: str = "/api/tts/chunk",
        volume_path: str = "/api/volume",
        queue_size: int = 100,
        wait_timeout: float = 0.1,
        max_chunk_chars: int = 80,
        max_body_bytes: int = 1_000_000,
        volume_getter: Callable[[], dict[str, Any]] | None = None,
        volume_setter: Callable[[Any], dict[str, Any]] | None = None,
        phase_getter: Callable[[], str] | None = None,
        shutdown_callback: Callable[[], None] | None = None,
        shutdown_token: str | None = None,
        module_name: str = "tts_service",
    ) -> None:
        self.request_path = _normalize_path(request_path)
        self.chunk_path = _normalize_path(chunk_path)
        self.volume_path = _normalize_path(volume_path)
        self.shutdown_path = "/shutdown"
        self.wait_timeout = wait_timeout
        self.max_body_bytes = max_body_bytes
        self.volume_getter = volume_getter
        self.volume_setter = volume_setter
        self.phase_getter = phase_getter or (lambda: "idle")
        self.shutdown_callback = shutdown_callback
        self.shutdown_token = shutdown_token
        self.module_name = module_name
        if shutdown_token is None and not _is_loopback_bind(host):
            raise ValueError("shutdown token is required when HTTP source is not bound to loopback")
        self._queue: queue.Queue[TtsRequest] = queue.Queue(maxsize=queue_size)
        self._chunker = StreamingTextChunker(max_chars=max_chunk_chars)
        self._server = _TtsThreadingHTTPServer((host, port), self._handler_class())
        self.host, self.port = self._server.server_address[:2]
        self.started_at_monotonic = time.monotonic()
        self._shutdown_event = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}{self.request_path}"

    @property
    def chunk_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}{self.chunk_path}"

    @property
    def volume_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}{self.volume_path}"

    @property
    def health_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/health"

    @property
    def shutdown_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}{self.shutdown_path}"

    @property
    def queued_count(self) -> int:
        return self._queue.qsize()

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    def next_request(self) -> TtsRequest | None:
        try:
            return self._queue.get(timeout=self.wait_timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._shutdown_event.set()
        if threading.current_thread() is not self._thread:
            self._server.shutdown()
            self._thread.join(timeout=1.0)
        self._server.server_close()

    def request_shutdown(self) -> None:
        first_request = not self._shutdown_event.is_set()
        self._shutdown_event.set()
        if not first_request:
            return
        if self.shutdown_callback is not None:
            try:
                self.shutdown_callback()
            except Exception:
                pass
        threading.Thread(target=self._server.shutdown, daemon=True).start()

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        source = self

        class Handler(BaseHTTPRequestHandler):
            def do_OPTIONS(self) -> None:
                _write_json(self, HTTPStatus.NO_CONTENT, None)

            def do_GET(self) -> None:
                source._handle_get(self)

            def do_POST(self) -> None:
                source._handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        if path == self.volume_path:
            self._handle_volume_get(handler)
            return
        if path != "/health":
            _write_json(handler, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        _write_json(
            handler,
            HTTPStatus.OK,
            {
                "ok": True,
                "module": self.module_name,
                "source": "http",
                "pid": os.getpid(),
                "uptime_s": round(time.monotonic() - self.started_at_monotonic, 3),
                "host": self.host,
                "port": self.port,
                "endpoint": self.endpoint,
                "chunk_endpoint": self.chunk_endpoint,
                "volume_endpoint": self.volume_endpoint,
                "shutdown_url": self.shutdown_endpoint,
                "queued": self.queued_count,
                "phase": self.phase_getter(),
            },
        )

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        if path == self.shutdown_path:
            self._handle_shutdown_post(handler)
            return
        if path == self.volume_path:
            self._handle_volume_post(handler)
            return
        if path not in {self.request_path, self.chunk_path}:
            _write_json(handler, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return

        try:
            payload = self._read_json_body(handler)
        except ValueError as exc:
            _write_json(handler, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        requests = self._requests_from_payload(payload, chunked=path == self.chunk_path)
        if not requests:
            if path == self.chunk_path and isinstance(payload, dict) and _is_final_payload(payload):
                _write_json(
                    handler,
                    HTTPStatus.ACCEPTED,
                    {"ok": True, "accepted": 0, "request_ids": []},
                )
                return
            _write_json(handler, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "no speakable text"})
            return

        try:
            for request in requests:
                self._queue.put_nowait(request)
        except queue.Full:
            _write_json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "tts queue full"})
            return

        _write_json(
            handler,
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "accepted": len(requests),
                "request_ids": [request.request_id for request in requests],
            },
        )

    def _handle_volume_get(self, handler: BaseHTTPRequestHandler) -> None:
        if self.volume_getter is None:
            _write_json(handler, HTTPStatus.NOT_FOUND, {"ok": False, "error": "volume API disabled"})
            return
        try:
            payload = self.volume_getter()
        except Exception as exc:
            _write_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        _write_json(handler, HTTPStatus.OK, payload)

    def _handle_volume_post(self, handler: BaseHTTPRequestHandler) -> None:
        if self.volume_setter is None:
            _write_json(handler, HTTPStatus.NOT_FOUND, {"ok": False, "error": "volume API disabled"})
            return
        try:
            payload = self._read_json_body(handler)
            response = self.volume_setter(payload)
        except ValueError as exc:
            _write_json(handler, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            _write_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        _write_json(handler, HTTPStatus.OK, response)

    def _handle_shutdown_post(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._shutdown_authorized(handler):
            _write_json(handler, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        _write_json(
            handler,
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "module": self.module_name,
                "shutting_down": True,
            },
        )
        threading.Thread(target=self._request_shutdown_after_response, daemon=True).start()

    def _request_shutdown_after_response(self) -> None:
        time.sleep(0.05)
        self.request_shutdown()

    def _shutdown_authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        if not self.shutdown_token:
            return True
        bearer = handler.headers.get("Authorization", "")
        if bearer == f"Bearer {self.shutdown_token}":
            return True
        return handler.headers.get("X-Sword-Agent-Token") == self.shutdown_token

    def _read_json_body(self, handler: BaseHTTPRequestHandler) -> Any:
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 1:
            raise ValueError("empty request body")
        if length > self.max_body_bytes:
            raise ValueError("request body too large")
        raw = handler.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc

    def _requests_from_payload(self, payload: Any, chunked: bool) -> list[TtsRequest]:
        if not chunked:
            request = request_from_sword_payload(payload, source="http")
            return [request] if request is not None else []
        return self._chunk_requests_from_payload(payload)

    def _chunk_requests_from_payload(self, payload: Any) -> list[TtsRequest]:
        if not isinstance(payload, dict):
            return []

        text = _find_string(payload, CHUNK_TEXT_PATHS) or ""
        final = _is_final_payload(payload)
        if not text and not final:
            return []

        turn_id = _find_string(payload, TURN_ID_PATHS)
        message_id = _find_string(payload, MESSAGE_ID_PATHS)
        conversation_id = _find_string(payload, CONVERSATION_ID_PATHS)
        stream_id = turn_id or message_id or conversation_id or "default"
        chunks = self._chunker.append(stream_id, text, final=final)

        requests: list[TtsRequest] = []
        for chunk in chunks:
            metadata: dict[str, Any] = {
                "chunk_index": chunk.index,
                "chunk_final": chunk.final,
            }
            if turn_id:
                metadata["turn_id"] = turn_id
            requests.append(
                TtsRequest(
                    text=chunk.text,
                    message_id=_chunk_message_id(message_id, stream_id, chunk.index),
                    conversation_id=conversation_id,
                    source="http_chunk",
                    metadata=metadata,
                )
            )
        return requests


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    return path if path.startswith("/") else f"/{path}"


def _find_string(payload: Any, paths: tuple[tuple[str, ...], ...]) -> str | None:
    for path in paths:
        value = _get_path(payload, path)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _get_path(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_final_payload(payload: dict[str, Any]) -> bool:
    if payload.get("final") is True or payload.get("done") is True:
        return True
    event = payload.get("event") or payload.get("type")
    return event in {"message_end", "done", "final", "llm_done"}


def _chunk_message_id(message_id: str | None, stream_id: str, index: int) -> str:
    base = message_id or stream_id
    return f"{base}:chunk:{index}"


class _TtsThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def _is_loopback_bind(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _write_json(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    payload: dict[str, Any] | None,
) -> None:
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Sword-Agent-Token")
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if body:
        handler.wfile.write(body)
