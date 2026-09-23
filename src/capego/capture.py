"""Capture and transmission run concurrently; only durable ACKs release the outbox."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Protocol

import httpx

from .contracts import EndRecording, Packet, PacketAck, RecordingSpec, canonical, sequence_digest
from .storage import StoreError


class Unavailable(Exception):
    """A transient transport failure; the same intent may be retried."""


class CacheFull(Exception):
    pass


class Transport(Protocol):
    def ready(self) -> dict: ...
    def create(self, spec: RecordingSpec) -> dict: ...
    def send(self, packet: Packet) -> PacketAck: ...
    def end(self, recording_id: str, end: EndRecording) -> dict: ...


class HTTPTransport:
    def __init__(self, url: str, token: str | None = None, timeout=10):
        self.client = httpx.Client(base_url=url.rstrip("/"), timeout=timeout,
                                   headers={"Authorization": f"Bearer {token}"} if token else {},
                                   trust_env=False)

    def request(self, method, path, body=None):
        try:
            response = self.client.request(method, path, json=body)
        except httpx.TransportError as exc:
            raise Unavailable(type(exc).__name__) from exc
        if response.status_code in {408, 425, 429, 500, 502, 503, 504, 507}:
            raise Unavailable(f"Receiver temporarily unavailable ({response.status_code})")
        if response.is_error:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            raise StoreError(error.get("code", "receiver_error"),
                             error.get("message", f"Receiver rejected request ({response.status_code})"),
                             response.status_code)
        return response.json()

    def ready(self):
        return self.request("GET", "/api/v1/ready")

    def create(self, spec):
        return self.request("POST", "/api/v1/recordings", spec.model_dump())

    def send(self, packet):
        value = self.request("PUT", f"/api/v1/recordings/{packet.recording_id}/packets/{packet.sequence}", packet.model_dump())
        return PacketAck.model_validate(value)

    def end(self, recording_id, end):
        return self.request("PUT", f"/api/v1/recordings/{recording_id}/end", end.model_dump())

    def close(self):
        self.client.close()


class Outbox:
    """SQLite spool keeps unacknowledged bodies; acknowledged rows retain only their digests."""

    def __init__(self, path: str | Path, max_bytes: int = 256 * 1024**2):
        if max_bytes < 1:
            raise ValueError("Cache capacity must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS packets (
              sequence INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, timestamp_ns INTEGER NOT NULL,
              body BLOB, size INTEGER NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def metadata(self, key):
        with self.connection() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_metadata(self, key, value):
        with self.connection() as db:
            old = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            body = canonical(value).decode()
            if old and old[0] != body:
                raise StoreError("outbox_conflict", "Outbox metadata is immutable")
            db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)", (key, body))

    def put(self, packet: Packet):
        body = packet.wire_bytes()
        with self.connection() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='end'").fetchone():
                raise StoreError("outbox_closed", "Cannot append to an ended capture")
            used = db.execute("SELECT COALESCE(SUM(size),0) FROM packets").fetchone()[0]
            expected = db.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            if packet.sequence != expected:
                raise StoreError("sequence_error", "Capture packets must be enqueued in sequence")
            if used + len(body) > self.max_bytes:
                raise CacheFull("Temporary transport cache is full")
            db.execute("INSERT INTO packets VALUES (?,?,?,?,?)", (packet.sequence, packet.digest(), packet.timestamp_ns, body, len(body)))

    def pending(self) -> Packet | None:
        with self.connection() as db:
            row = db.execute("SELECT body FROM packets WHERE body IS NOT NULL ORDER BY sequence LIMIT 1").fetchone()
        return Packet.model_validate_json(row[0]) if row else None

    def acknowledge(self, packet: Packet, ack: PacketAck):
        if ack.recording_id != packet.recording_id or ack.sequence != packet.sequence or ack.sha256 != packet.digest() or ack.durable is not True:
            raise StoreError("bad_ack", "ACK does not confirm the exact packet")
        with self.connection() as db:
            db.execute("UPDATE packets SET body=NULL,size=0 WHERE sequence=? AND sha256=?", (packet.sequence, ack.sha256))

    def freeze(self, reason: str, ended_at_ns: int | None = None) -> EndRecording:
        previous = self.metadata("end")
        if previous:
            return EndRecording.model_validate(previous)
        with self.connection() as db:
            rows = db.execute("SELECT sequence,sha256,timestamp_ns FROM packets ORDER BY sequence").fetchall()
            last_time = max((r["timestamp_ns"] for r in rows), default=0)
            end = EndRecording(packet_count=len(rows), content_sha256=sequence_digest([(r["sequence"], r["sha256"]) for r in rows]),
                               ended_at_ns=max(last_time, ended_at_ns or 0), reason=reason)
            db.execute("INSERT INTO metadata VALUES ('end',?)", (canonical(end.model_dump()).decode(),))
        return end

    def stats(self):
        with self.connection() as db:
            row = db.execute("SELECT COUNT(*) produced, COUNT(body) pending, COALESCE(SUM(size),0) cache_bytes FROM packets").fetchone()
        return dict(row)


class CaptureSession:
    def __init__(self, spec: RecordingSpec, transport: Transport, outbox: Outbox, retry_delay=0.1):
        self.spec, self.transport, self.outbox = spec, transport, outbox
        self.retry_delay = retry_delay
        self.stop_capture = threading.Event()
        self.stop_sender = threading.Event()
        self.sender: threading.Thread | None = None
        self.error: str | None = None
        self.last_transport_error: str | None = None
        self.end_acknowledged = False

    def start(self):
        if self.outbox.metadata("spec") or self.outbox.stats()["produced"]:
            raise StoreError("outbox_in_use", "Use resume for an existing outbox")
        if not self.transport.ready().get("ready"):
            raise Unavailable("Receiver is not ready")
        self.transport.create(self.spec)
        self.outbox.set_metadata("spec", self.spec.model_dump())
        self._start_sender()

    def _start_sender(self):
        self.sender = threading.Thread(target=self._pump, name=f"capego-send-{self.spec.id}", daemon=True)
        self.sender.start()

    def _pump(self):
        while not self.stop_sender.is_set():
            try:
                end = self.outbox.metadata("end")
                if end and not self.end_acknowledged:
                    self.transport.end(self.spec.id, EndRecording.model_validate(end))
                    self.end_acknowledged = True
                packet = self.outbox.pending()
                if packet:
                    self.outbox.acknowledge(packet, self.transport.send(packet))
                    self.last_transport_error = None
                    continue
                if end and self.end_acknowledged:
                    return
            except Unavailable as exc:
                self.last_transport_error = str(exc)
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.stop_capture.set()
                return
            self.stop_sender.wait(self.retry_delay)

    def record(self, packets: Iterable[Packet], realtime=True, duration_ns: int | None = None):
        if self.sender is None:
            self.start()
        start = time.monotonic()
        reason = "source_exhausted"
        try:
            for packet in packets:
                if packet.recording_id != self.spec.id:
                    raise ValueError("Source packet belongs to a different recording")
                if self.stop_capture.is_set():
                    reason = "interrupted" if self.error else "user"
                    break
                if realtime:
                    wait = packet.timestamp_ns / 1e9 - (time.monotonic() - start)
                    if wait > 0 and self.stop_capture.wait(wait):
                        reason = "interrupted" if self.error else "user"
                        break
                self.outbox.put(packet)
        except CacheFull:
            reason = "cache_full"
        except KeyboardInterrupt:
            reason = "user"
        except Exception:
            self.outbox.freeze("source_error")
            raise
        end = self.outbox.freeze(reason, duration_ns if reason == "source_exhausted" else None)
        return end

    def wait_saved(self, timeout=30) -> bool:
        if self.sender:
            self.sender.join(timeout)
        return not self.error and self.end_acknowledged and self.outbox.stats()["pending"] == 0

    def close(self):
        self.stop_capture.set()
        self.stop_sender.set()
        if self.sender:
            self.sender.join(12)

    @classmethod
    def resume(cls, transport: Transport, outbox: Outbox):
        spec = RecordingSpec.model_validate(outbox.metadata("spec"))
        transport.create(spec)
        session = cls(spec, transport, outbox)
        # Recovery only drains existing bytes. It never restarts acquisition.
        if not outbox.metadata("end"):
            outbox.freeze("interrupted")
        session._start_sender()
        return session
