import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


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

        while True:
            with session.condition:
                while True:
                    if next_index < session.first_index:
                        next_index = session.first_index

                    available = [chunk for chunk in session.chunks if chunk.index >= next_index]
                    if available:
                        break
                    if session.closed:
                        return
                    session.condition.wait(timeout=15)
                    if session.closed and next_index >= session.next_index:
                        return

                for chunk in available:
                    next_index = chunk.index + 1
                    yield chunk.data

    def get_session(self, session_token: str) -> LiveAudioSessionState | None:
        with self._lock:
            return self._sessions.get(session_token)


live_audio_broker = LiveAudioBroker()
