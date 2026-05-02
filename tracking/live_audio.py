import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

# Keep-alive cadence on the parent's download stream while no real audio
# is queued yet. The frame is deliberately large enough (8 KB ≈ 250 ms of
# 16 kHz s16le silence) to push past common nginx / wsgi output buffers,
# so the parent's HTTP client gets bytes immediately instead of sitting
# on `awaiting first byte` while data accumulates in an upstream buffer.
_KEEPALIVE_INTERVAL_SECONDS = 1.0
_KEEPALIVE_FRAME_BYTES = 16000 * 2 // 4  # 250 ms of 16 kHz s16le silence
_KEEPALIVE_FRAME = b"\x00" * _KEEPALIVE_FRAME_BYTES
# Primer is bigger still so even a 16 KB proxy buffer flushes immediately
# when the parent connects. Plays as ~0.5 s of silence — imperceptible.
_PRIMER_FRAME = b"\x00" * (16 * 1024)


@dataclass
class LiveAudioChunk:
    index: int
    data: bytes


@dataclass
class LiveAudioSessionState:
    child_id: int
    sample_rate: int = 16000
    channels: int = 1
    format: str = "pcm_s16le"
    closed: bool = False
    next_index: int = 1
    first_index: int = 1
    buffered_bytes: int = 0
    chunks: Deque[LiveAudioChunk] = field(default_factory=deque)
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )


class LiveAudioBroker:
    """In-memory broker for one long-running PCM stream per session token."""

    def __init__(self, max_buffer_bytes: int = 512 * 1024):
        self._sessions: dict[str, LiveAudioSessionState] = {}
        self._lock = threading.RLock()
        self._max_buffer_bytes = max_buffer_bytes

    def get_or_create(
        self,
        session_token: str,
        *,
        child_id: int,
        sample_rate: int = 16000,
        channels: int = 1,
        audio_format: str = "pcm_s16le",
    ) -> LiveAudioSessionState:
        with self._lock:
            session = self._sessions.get(session_token)
            if session is None:
                session = LiveAudioSessionState(
                    child_id=child_id,
                    sample_rate=sample_rate,
                    channels=channels,
                    format=audio_format,
                )
                self._sessions[session_token] = session
                return session

            session.child_id = child_id
            session.sample_rate = sample_rate
            session.channels = channels
            session.format = audio_format
            if session.closed:
                session.closed = False
            return session

    def publish(self, session_token: str, *, child_id: int, data: bytes) -> None:
        if not data:
            return
        session = self.get_or_create(session_token, child_id=child_id)
        with session.condition:
            chunk = LiveAudioChunk(index=session.next_index, data=data)
            session.next_index += 1
            session.chunks.append(chunk)
            session.buffered_bytes += len(data)

            while session.buffered_bytes > self._max_buffer_bytes and session.chunks:
                dropped = session.chunks.popleft()
                session.buffered_bytes -= len(dropped.data)
                session.first_index = dropped.index + 1

            session.condition.notify_all()

    def finish(self, session_token: str, *, child_id: int | None = None) -> None:
        with self._lock:
            session = self._sessions.get(session_token)
        if session is None:
            return
        if child_id is not None and session.child_id != child_id:
            return
        with session.condition:
            session.closed = True
            session.condition.notify_all()

    def iter_chunks(self, session_token: str, *, child_id: int):
        session = self.get_or_create(session_token, child_id=child_id)
        next_index = session.first_index
        last_emit = time.monotonic()

        # Prime the response so the WSGI server flushes headers and the
        # first body bytes immediately — otherwise nginx / uwsgi may sit
        # waiting on a partial 8/16 KB buffer and 504 the parent before
        # the child's upload pipeline has started.
        yield _PRIMER_FRAME

        while True:
            with session.condition:
                if next_index < session.first_index:
                    next_index = session.first_index

                available = [chunk for chunk in session.chunks if chunk.index >= next_index]
                if not available:
                    if session.closed:
                        return
                    session.condition.wait(timeout=_KEEPALIVE_INTERVAL_SECONDS)
                    if session.closed and next_index >= session.next_index:
                        return
                    available = [chunk for chunk in session.chunks if chunk.index >= next_index]

                for chunk in available:
                    next_index = chunk.index + 1

            if available:
                for chunk in available:
                    yield chunk.data
                last_emit = time.monotonic()
            elif time.monotonic() - last_emit >= _KEEPALIVE_INTERVAL_SECONDS:
                # No real audio yet — emit silence so the connection (and the
                # parent's audio sink) stays warm while the child wakes up.
                yield _KEEPALIVE_FRAME
                last_emit = time.monotonic()

    def get_session(self, session_token: str) -> LiveAudioSessionState | None:
        with self._lock:
            return self._sessions.get(session_token)


live_audio_broker = LiveAudioBroker()
