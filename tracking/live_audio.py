import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Cross-process live-audio relay.
#
# The previous implementation kept the audio stream in an in-memory dict.
# That only works when the child's upload POST and the parent's download GET
# land in the SAME process. Production runs gunicorn with several workers
# (see DEPLOY_NGINX.md), so the two requests routinely hit different worker
# processes and the parent only ever heard silence — the classic "listen
# around stopped working" bug.
#
# This version relays the PCM stream through a small append-only file per
# session on a RAM-backed tmpfs (`/dev/shm`). Any worker (any process) can
# write to / tail the same file, so it works with any `--workers` count and
# needs no Redis or external broker.
# ---------------------------------------------------------------------------

# Keep-alive cadence on the parent's download stream while no real audio is
# queued yet. Large enough (8 KB ≈ 250 ms of 16 kHz s16le silence) to push
# past common nginx / wsgi output buffers so the parent's HTTP client gets
# bytes immediately instead of sitting on "awaiting first byte".
_KEEPALIVE_INTERVAL_SECONDS = 1.0
_KEEPALIVE_FRAME_BYTES = 16000 * 2 // 4  # 250 ms of 16 kHz s16le silence
_KEEPALIVE_FRAME = b"\x00" * _KEEPALIVE_FRAME_BYTES
# Primer is bigger still so even a 16 KB proxy buffer flushes immediately
# when the parent connects. Plays as ~0.5 s of silence — imperceptible.
_PRIMER_FRAME = b"\x00" * (16 * 1024)

# How fast a parent reader polls the shared file for freshly-appended bytes.
# 40 ms keeps end-to-end latency low without burning CPU.
_TAIL_POLL_SECONDS = 0.04
# Max bytes a reader will pull per loop iteration.
_READ_CHUNK_BYTES = 64 * 1024
# When a parent connects mid-session, start this far behind the live edge
# (~0.25 s of audio) instead of replaying the whole file — keeps it "live".
_LIVE_TAIL_BYTES = 8 * 1024
# A session directory with no writes for this long is considered dead and is
# reaped so /dev/shm doesn't accumulate stale files.
_SESSION_TTL_SECONDS = 15 * 60
# Reaping walks the directory; only do it occasionally per process.
_REAP_INTERVAL_SECONDS = 30.0
# Hard cap on a parent generator that never receives real audio, so a
# forgotten/broken listen session can't tie up a worker thread forever.
_IDLE_STREAM_TIMEOUT_SECONDS = 5 * 60


@dataclass
class LiveAudioSessionState:
    child_id: int
    sample_rate: int = 16000
    channels: int = 1
    format: str = "pcm_s16le"
    closed: bool = False


def _base_dir() -> str:
    # Prefer /dev/shm (RAM-backed tmpfs on Linux) for the lowest-latency,
    # cross-process relay. Fall back to the system temp dir elsewhere.
    for candidate in ("/dev/shm", tempfile.gettempdir()):
        if candidate and os.path.isdir(candidate):
            root = os.path.join(candidate, "baby_locator_live_audio")
            try:
                os.makedirs(root, exist_ok=True)
                return root
            except OSError:
                continue
    root = os.path.join(tempfile.gettempdir(), "baby_locator_live_audio")
    os.makedirs(root, exist_ok=True)
    return root


class LiveAudioBroker:
    """File-backed broker for one long-running PCM stream per session token."""

    def __init__(self):
        self._root = _base_dir()
        # Per-thread cache of the append file descriptor for the session an
        # upload thread is currently writing, so we don't reopen per chunk.
        self._local = threading.local()
        self._reap_lock = threading.Lock()
        self._last_reap = 0.0

    # -- path helpers -------------------------------------------------------

    def _session_dir(self, session_token: str) -> str:
        # session_token is a uuid4 hex string (see AroundAudioClip), but guard
        # against path traversal regardless.
        safe = os.path.basename(session_token)
        return os.path.join(self._root, safe)

    @staticmethod
    def _meta_path(session_dir: str) -> str:
        return os.path.join(session_dir, "meta.json")

    @staticmethod
    def _data_path(session_dir: str) -> str:
        return os.path.join(session_dir, "stream.pcm")

    def _read_meta(self, meta_path: str) -> dict | None:
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def _write_meta(self, meta_path: str, meta: dict) -> None:
        # Atomic replace so a concurrent reader never sees a half-written file.
        directory = os.path.dirname(meta_path)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)
            os.replace(tmp, meta_path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # -- public API ---------------------------------------------------------

    def get_or_create(
        self,
        session_token: str,
        *,
        child_id: int,
        sample_rate: int = 16000,
        channels: int = 1,
        audio_format: str = "pcm_s16le",
    ) -> LiveAudioSessionState:
        self._maybe_reap()
        session_dir = self._session_dir(session_token)
        meta_path = self._meta_path(session_dir)

        existing = self._read_meta(meta_path)
        if existing is None:
            os.makedirs(session_dir, exist_ok=True)
            # Create (or keep) the append-only data file.
            open(self._data_path(session_dir), "ab").close()
            meta = {
                "child_id": child_id,
                "sample_rate": sample_rate,
                "channels": channels,
                "format": audio_format,
                "closed": False,
                "created_at": time.time(),
            }
            self._write_meta(meta_path, meta)
            return LiveAudioSessionState(
                child_id=child_id,
                sample_rate=sample_rate,
                channels=channels,
                format=audio_format,
            )

        if int(existing.get("child_id", child_id)) != int(child_id):
            raise PermissionError(
                f"Session token belongs to child {existing.get('child_id')}, "
                f"cannot rebind to {child_id}"
            )

        existing["sample_rate"] = sample_rate
        existing["channels"] = channels
        existing["format"] = audio_format
        existing["closed"] = False
        self._write_meta(meta_path, existing)
        return LiveAudioSessionState(
            child_id=int(existing["child_id"]),
            sample_rate=sample_rate,
            channels=channels,
            format=audio_format,
        )

    def _writer_fd(self, session_token: str, session_dir: str) -> int:
        cache = getattr(self._local, "writers", None)
        if cache is None:
            cache = {}
            self._local.writers = cache
        fd = cache.get(session_token)
        if fd is not None:
            return fd
        fd = os.open(
            self._data_path(session_dir),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        cache[session_token] = fd
        return fd

    def publish(self, session_token: str, *, child_id: int, data: bytes) -> None:
        if not data:
            return
        session_dir = self._session_dir(session_token)
        if not os.path.isdir(session_dir):
            # Parent may not have opened the stream yet; create the session so
            # the child's audio is buffered until the parent tails in.
            self.get_or_create(session_token, child_id=child_id)
        fd = self._writer_fd(session_token, session_dir)
        try:
            # O_APPEND makes each write land atomically at the end of the file
            # across processes, so a reconnecting upload never clobbers data.
            os.write(fd, data)
        except OSError:
            # Drop the cached fd so the next publish reopens the file.
            self._drop_writer(session_token)
            raise

    def _drop_writer(self, session_token: str) -> None:
        cache = getattr(self._local, "writers", None)
        if not cache:
            return
        fd = cache.pop(session_token, None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def finish(self, session_token: str, *, child_id: int | None = None) -> None:
        self._drop_writer(session_token)
        session_dir = self._session_dir(session_token)
        meta_path = self._meta_path(session_dir)
        meta = self._read_meta(meta_path)
        if meta is None:
            return
        if child_id is not None and int(meta.get("child_id", child_id)) != int(child_id):
            return
        meta["closed"] = True
        self._write_meta(meta_path, meta)

    def iter_chunks(self, session_token: str, *, child_id: int):
        session_dir = self._session_dir(session_token)
        # Make sure the session exists so a parent that connects first still
        # gets a file to tail.
        self.get_or_create(session_token, child_id=child_id)
        data_path = self._data_path(session_dir)
        meta_path = self._meta_path(session_dir)

        # Prime the response so the WSGI server flushes headers and the first
        # body bytes immediately.
        yield _PRIMER_FRAME

        try:
            reader = open(data_path, "rb")
        except OSError:
            return

        try:
            # Start near the live edge rather than replaying the whole buffer.
            size = os.fstat(reader.fileno()).st_size
            start = max(0, size - _LIVE_TAIL_BYTES)
            start -= start % 2  # keep 16-bit sample alignment
            reader.seek(start)

            now = time.monotonic()
            last_emit = now
            last_real_audio = now

            while True:
                chunk = reader.read(_READ_CHUNK_BYTES)
                if chunk:
                    yield chunk
                    now = time.monotonic()
                    last_emit = now
                    last_real_audio = now
                    continue

                meta = self._read_meta(meta_path)
                if meta is None:
                    # Session directory was reaped — nothing more to send.
                    return
                if meta.get("closed"):
                    # Confirm we've drained everything the writer flushed.
                    tail = reader.read(_READ_CHUNK_BYTES)
                    if tail:
                        yield tail
                        last_emit = time.monotonic()
                        last_real_audio = last_emit
                        continue
                    return

                now = time.monotonic()
                if now - last_real_audio >= _IDLE_STREAM_TIMEOUT_SECONDS:
                    # Child never produced audio (or stopped long ago); don't
                    # tie up a worker thread forever.
                    return
                if now - last_emit >= _KEEPALIVE_INTERVAL_SECONDS:
                    yield _KEEPALIVE_FRAME
                    last_emit = now
                time.sleep(_TAIL_POLL_SECONDS)
        finally:
            try:
                reader.close()
            except OSError:
                pass

    def get_session(self, session_token: str) -> LiveAudioSessionState | None:
        meta = self._read_meta(self._meta_path(self._session_dir(session_token)))
        if meta is None:
            return None
        return LiveAudioSessionState(
            child_id=int(meta.get("child_id", 0)),
            sample_rate=int(meta.get("sample_rate", 16000)),
            channels=int(meta.get("channels", 1)),
            format=str(meta.get("format", "pcm_s16le")),
            closed=bool(meta.get("closed", False)),
        )

    # -- housekeeping -------------------------------------------------------

    def _maybe_reap(self) -> None:
        now = time.monotonic()
        if now - self._last_reap < _REAP_INTERVAL_SECONDS:
            return
        if not self._reap_lock.acquire(blocking=False):
            return
        try:
            self._last_reap = now
            cutoff = time.time() - _SESSION_TTL_SECONDS
            for name in os.listdir(self._root):
                session_dir = os.path.join(self._root, name)
                data_path = self._data_path(session_dir)
                try:
                    mtime = os.path.getmtime(data_path)
                except OSError:
                    # No data file (or dir vanished) — try meta, else remove.
                    try:
                        mtime = os.path.getmtime(self._meta_path(session_dir))
                    except OSError:
                        shutil.rmtree(session_dir, ignore_errors=True)
                        continue
                if mtime < cutoff:
                    shutil.rmtree(session_dir, ignore_errors=True)
        except OSError:
            pass
        finally:
            self._reap_lock.release()


live_audio_broker = LiveAudioBroker()
