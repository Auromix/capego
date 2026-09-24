"""Durable packet store. ACK follows file fsync + index transaction commit."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .contracts import (
    EndRecording,
    Packet,
    PacketAck,
    RecordingSpec,
    canonical,
    sequence_digest,
    sha256,
)


class StoreError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value):
        raise StoreError("invalid_id", "Invalid resource identifier", 422)
    return value


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Store:
    def __init__(self, root: str | Path, min_free_bytes: int = 64 * 1024**2):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.min_free_bytes = min_free_bytes
        with self.connection(write=True) as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS recordings (
              id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
              end_spec TEXT, created_at TEXT NOT NULL, error TEXT);
            CREATE TABLE IF NOT EXISTS packets (
              recording_id TEXT NOT NULL REFERENCES recordings(id), sequence INTEGER NOT NULL,
              timestamp_ns INTEGER NOT NULL, stream_id TEXT NOT NULL, sha256 TEXT NOT NULL,
              path TEXT NOT NULL, bytes INTEGER NOT NULL,
              PRIMARY KEY(recording_id,sequence));
            CREATE INDEX IF NOT EXISTS packet_time ON packets(recording_id,timestamp_ns,sequence);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(id),
              batch_id TEXT NOT NULL, status TEXT NOT NULL, config TEXT NOT NULL,
              result TEXT, error TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews (
              processing_id TEXT NOT NULL REFERENCES jobs(id), segment_id TEXT NOT NULL,
              revision INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(processing_id,segment_id,revision));
            CREATE TABLE IF NOT EXISTS datasets (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL,
              sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.root / "index.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ready(self) -> dict:
        free = shutil.disk_usage(self.root).free
        if free < self.min_free_bytes:
            raise StoreError("storage_unavailable", "PC storage has insufficient free space", 507)
        try:
            with tempfile.TemporaryFile(dir=self.root) as probe:
                probe.write(b"capego-ready")
                probe.flush()
                os.fsync(probe.fileno())
        except OSError as exc:
            raise StoreError("storage_unavailable", "PC storage is not writable", 503) from exc
        return {"ready": True, "free_bytes": free, "schema_version": 1}

    def create(self, spec: RecordingSpec) -> dict:
        self.ready()
        body = canonical(spec.model_dump()).decode()
        with self.connection(write=True) as db:
            existing = db.execute("SELECT spec FROM recordings WHERE id=?", (spec.id,)).fetchone()
            if existing:
                if existing["spec"] != body:
                    raise StoreError(
                        "recording_conflict", "Recording ID already has different metadata"
                    )
            else:
                folder = self.root / "recordings" / spec.id
                atomic_write(folder / "recording.json", body.encode())
                fsync_dir(folder.parent)
                db.execute(
                    "INSERT INTO recordings VALUES (?,?,?,NULL,?,NULL)",
                    (spec.id, body, "recording", utc_now()),
                )
        return self.recording(spec.id)

    def recording(self, recording_id: str) -> dict:
        safe_id(recording_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if row is None:
                raise StoreError("not_found", "Recording not found", 404)
            stats = db.execute(
                "SELECT COUNT(*) count, COALESCE(SUM(bytes),0) bytes FROM packets WHERE recording_id=?",
                (recording_id,),
            ).fetchone()
        return {
            "id": recording_id,
            "spec": json.loads(row["spec"]),
            "status": row["status"],
            "end": json.loads(row["end_spec"]) if row["end_spec"] else None,
            "created_at": row["created_at"],
            "error": row["error"],
            **dict(stats),
        }

    def recordings(self, limit=100, offset=0) -> dict:
        with self.connection() as db:
            ids = db.execute(
                "SELECT id FROM recordings ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            count = db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        return {
            "items": [self.recording(r["id"]) for r in ids],
            "total": count,
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def validate_payload(packet: Packet, spec: RecordingSpec) -> None:
        stream = next((s for s in spec.streams if s.id == packet.stream_id), None)
        if stream is None:
            raise StoreError("unknown_stream", "Packet references an undeclared stream", 422)
        try:
            payload = packet.payload()
            if stream.kind == "rgb":
                if packet.codec not in {"jpeg", "png"}:
                    raise ValueError("RGB packet requires image codec")
                with Image.open(io.BytesIO(payload)) as img:
                    if img.size != (stream.width, stream.height):
                        raise ValueError("Image dimensions do not match stream")
                    if img.format != {"jpeg": "JPEG", "png": "PNG"}[packet.codec]:
                        raise ValueError("Image codec does not match bytes")
                    img.verify()
            elif stream.kind == "tracking":
                from .geometry import TrackingFrame

                if packet.codec != "tracking_json":
                    raise ValueError("Tracking packet requires tracking_json codec")
                frame = TrackingFrame.model_validate_json(payload)
                if frame.timestamp_ns != packet.timestamp_ns:
                    raise ValueError("Tracking payload timestamp differs from packet")
            else:
                if packet.codec != "imu_json":
                    raise ValueError("IMU packet requires imu_json codec")
                value = json.loads(payload)
                if set(value) != {"accel_m_s2", "gyro_rad_s"}:
                    raise ValueError("Expected six-axis IMU in SI units")
                for vector in value.values():
                    if not isinstance(vector, list) or len(vector) != 3:
                        raise ValueError("Each IMU vector must have three components")
                    canonical(vector)
                    if not all(type(x) in (int, float) for x in vector):
                        raise ValueError("IMU components must be numbers")
        except (ValueError, TypeError, OSError, KeyError) as exc:
            raise StoreError("invalid_payload", str(exc), 422) from exc

    def receive(self, packet: Packet) -> PacketAck:
        encoded = packet.wire_bytes()
        digest = sha256(encoded)
        with self.connection(write=True) as db:
            rec = db.execute(
                "SELECT * FROM recordings WHERE id=?", (packet.recording_id,)
            ).fetchone()
            if rec is None:
                raise StoreError("not_found", "Create recording before sending packets", 404)
            existing = db.execute(
                "SELECT * FROM packets WHERE recording_id=? AND sequence=?",
                (packet.recording_id, packet.sequence),
            ).fetchone()
            if existing:
                if existing["sha256"] != digest:
                    raise StoreError("packet_conflict", "Sequence already contains different data")
                path = self.root / existing["path"]
                if not path.is_file() or sha256(path.read_bytes()) != digest:
                    raise StoreError(
                        "integrity_error", "Previously stored packet failed verification", 409
                    )
            else:
                if rec["status"] == "complete":
                    raise StoreError("recording_closed", "Cannot append to a completed recording")
                spec = RecordingSpec.model_validate_json(rec["spec"])
                if rec["end_spec"]:
                    end = EndRecording.model_validate_json(rec["end_spec"])
                    if (
                        packet.sequence >= end.packet_count
                        or packet.timestamp_ns >= end.ended_at_ns
                    ):
                        raise StoreError(
                            "outside_recording", "Packet falls outside the frozen recording"
                        )
                self.validate_payload(packet, spec)
                self.ready()
                bucket = packet.timestamp_ns // spec.chunk_duration_ns
                path = (
                    self.root
                    / "recordings"
                    / packet.recording_id
                    / "chunks"
                    / f"{bucket:08d}"
                    / f"{packet.sequence:012d}.json"
                )
                atomic_write(path, encoded)
                fsync_dir(path.parent.parent)
                fsync_dir(path.parent.parent.parent)
                db.execute(
                    "INSERT INTO packets VALUES (?,?,?,?,?,?,?)",
                    (
                        packet.recording_id,
                        packet.sequence,
                        packet.timestamp_ns,
                        packet.stream_id,
                        digest,
                        str(path.relative_to(self.root)),
                        len(encoded),
                    ),
                )
        current = self.recording(packet.recording_id)
        if current["end"] and current["count"] >= current["end"]["packet_count"]:
            self.verify(packet.recording_id)
        return PacketAck(recording_id=packet.recording_id, sequence=packet.sequence, sha256=digest)

    def end(self, recording_id: str, end: EndRecording) -> dict:
        safe_id(recording_id)
        body = canonical(end.model_dump()).decode()
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if row is None:
                raise StoreError("not_found", "Recording not found", 404)
            if row["end_spec"] and row["end_spec"] != body:
                raise StoreError("end_conflict", "Recording boundary is already frozen")
            if not row["end_spec"]:
                db.execute(
                    "UPDATE recordings SET end_spec=?,status='awaiting_data' WHERE id=?",
                    (body, recording_id),
                )
                atomic_write(self.root / "recordings" / recording_id / "end.json", body.encode())
        return self.verify(recording_id)

    def verify(self, recording_id: str) -> dict:
        safe_id(recording_id)
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if row is None:
                raise StoreError("not_found", "Recording not found", 404)
            if not row["end_spec"]:
                raise StoreError(
                    "still_recording", "End recording before completeness verification"
                )
            end = EndRecording.model_validate_json(row["end_spec"])
            packets = db.execute(
                "SELECT * FROM packets WHERE recording_id=? ORDER BY sequence", (recording_id,)
            ).fetchall()
            error = None
            if len(packets) < end.packet_count:
                status = "awaiting_data"
            else:
                status = "complete"
                try:
                    folder = self.root / "recordings" / recording_id
                    if (folder / "recording.json").read_bytes() != row["spec"].encode() or (
                        folder / "end.json"
                    ).read_bytes() != row["end_spec"].encode():
                        raise ValueError("Recording metadata file differs from frozen index")
                    if [p["sequence"] for p in packets] != list(range(end.packet_count)):
                        raise ValueError("Packet sequence does not match recording end manifest")
                    if (
                        sequence_digest([(p["sequence"], p["sha256"]) for p in packets])
                        != end.content_sha256
                    ):
                        raise ValueError("Recording content digest mismatch")
                    last_times = {}
                    for p in packets:
                        data = (self.root / p["path"]).read_bytes()
                        if sha256(data) != p["sha256"]:
                            raise ValueError(f"Corrupt packet {p['sequence']}")
                        if p["timestamp_ns"] >= end.ended_at_ns:
                            raise ValueError("Packet time exceeds recording end")
                        if p["timestamp_ns"] <= last_times.get(p["stream_id"], -1):
                            raise ValueError("Per-stream capture timestamps must increase")
                        last_times[p["stream_id"]] = p["timestamp_ns"]
                except (ValueError, OSError) as exc:
                    status, error = "integrity_failed", str(exc)
            db.execute(
                "UPDATE recordings SET status=?,error=? WHERE id=?", (status, error, recording_id)
            )
        return self.recording(recording_id)

    def packet_rows(self, recording_id: str, stream_id: str | None = None) -> list[dict]:
        self.recording(recording_id)
        with self.connection() as db:
            query = "SELECT * FROM packets WHERE recording_id=?"
            args = [recording_id]
            if stream_id:
                query += " AND stream_id=?"
                args.append(stream_id)
            query += " ORDER BY timestamp_ns,sequence"
            return [dict(r) for r in db.execute(query, args)]

    def read_packet(self, row: dict) -> Packet:
        data = (self.root / row["path"]).read_bytes()
        if sha256(data) != row["sha256"]:
            raise StoreError("integrity_error", "Packet checksum mismatch")
        return Packet.model_validate_json(data)

    def require_complete(self, recording_id: str) -> dict:
        rec = self.recording(recording_id)
        if not rec["end"]:
            raise StoreError(
                "not_complete", "Recording must end and be fully saved before processing"
            )
        rec = self.verify(recording_id)
        if rec["status"] != "complete":
            raise StoreError("not_complete", "Recording is incomplete or corrupt")
        return rec
