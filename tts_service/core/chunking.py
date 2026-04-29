from __future__ import annotations

from dataclasses import dataclass


DEFAULT_BOUNDARIES = (".", "!", "?", "。", "！", "？", "\n")


@dataclass
class TextChunk:
    index: int
    text: str
    final: bool = False


class StreamingTextChunker:
    def __init__(
        self,
        max_chars: int = 80,
        boundaries: tuple[str, ...] = DEFAULT_BOUNDARIES,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        self.max_chars = max_chars
        self.boundaries = boundaries
        self._buffers: dict[str, str] = {}
        self._next_indexes: dict[str, int] = {}

    def append(self, stream_id: str, text: str, final: bool = False) -> list[TextChunk]:
        stream_key = stream_id or "default"
        self._buffers[stream_key] = self._buffers.get(stream_key, "") + text
        self._next_indexes.setdefault(stream_key, 0)

        chunks: list[TextChunk] = []
        while True:
            cut_at = _next_cut(self._buffers[stream_key], self.boundaries, self.max_chars)
            if cut_at is None:
                break
            chunk_text = self._buffers[stream_key][:cut_at].strip()
            self._buffers[stream_key] = self._buffers[stream_key][cut_at:].lstrip()
            if chunk_text:
                chunks.append(self._build_chunk(stream_key, chunk_text))

        if final:
            remainder = self._buffers.get(stream_key, "").strip()
            if remainder:
                chunks.append(self._build_chunk(stream_key, remainder, final=True))
            elif chunks:
                chunks[-1].final = True
            self._buffers.pop(stream_key, None)
            self._next_indexes.pop(stream_key, None)

        return chunks

    def _build_chunk(self, stream_key: str, text: str, final: bool = False) -> TextChunk:
        index = self._next_indexes[stream_key]
        self._next_indexes[stream_key] = index + 1
        return TextChunk(index=index, text=text, final=final)


def _next_cut(text: str, boundaries: tuple[str, ...], max_chars: int) -> int | None:
    if not text:
        return None
    boundary_indexes = [text.find(boundary) for boundary in boundaries if boundary and text.find(boundary) >= 0]
    if boundary_indexes:
        return min(boundary_indexes) + 1
    if len(text) >= max_chars:
        return max_chars
    return None
