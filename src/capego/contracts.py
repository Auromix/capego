"""Version 1 wire contracts. Sensor time is recording-relative integer nanoseconds."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sequence_digest(items: list[tuple[int, str]]) -> str:
    return sha256(canonical([[seq, digest] for seq, digest in sorted(items)]))


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Stream(Contract):
    id: Identifier
    kind: Literal["rgb", "imu"]
    rate_hz: float = Field(gt=0, le=10000)
    width: int | None = Field(default=None, gt=0, le=8192)
    height: int | None = Field(default=None, gt=0, le=8192)

    @model_validator(mode="after")
    def dimensions(self):
        if self.kind == "rgb" and (self.width is None or self.height is None):
            raise ValueError("RGB streams require width and height")
        return self


class RecordingSpec(Contract):
    schema_version: Literal[1] = 1
    id: Identifier
    device_id: Identifier
    origin: Literal["synthetic", "replay", "sensor"]
    streams: list[Stream] = Field(min_length=1, max_length=16)
    chunk_duration_ns: int = Field(default=5_000_000_000, gt=0)
    started_at: str
    calibration: dict = Field(default_factory=dict)
    clock: dict = Field(default_factory=lambda: {"unit": "ns", "reference": "recording_start"})

    @model_validator(mode="after")
    def unique_streams(self):
        if len({s.id for s in self.streams}) != len(self.streams):
            raise ValueError("Stream IDs must be unique")
        return self


class Packet(Contract):
    schema_version: Literal[1] = 1
    recording_id: Identifier
    sequence: int = Field(ge=0, le=2**53 - 1)
    stream_id: Identifier
    timestamp_ns: int = Field(ge=0, le=2**63 - 1)
    source_timestamp_ns: int = Field(ge=0, le=2**63 - 1)
    clock_id: Identifier = "capture_monotonic"
    codec: Literal["jpeg", "png", "imu_json"]
    payload_b64: str = Field(max_length=12_000_000)

    def payload(self) -> bytes:
        try:
            data = base64.b64decode(self.payload_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("Invalid base64 payload") from exc
        if not data:
            raise ValueError("Empty payload")
        return data

    def wire_bytes(self) -> bytes:
        return canonical(self.model_dump())

    def digest(self) -> str:
        return sha256(self.wire_bytes())


class EndRecording(Contract):
    packet_count: int = Field(ge=0, le=2**53 - 1)
    content_sha256: Digest
    ended_at_ns: int = Field(ge=0, le=2**63 - 1)
    reason: Literal["user", "source_exhausted", "cache_full", "source_error", "interrupted"]


class PacketAck(Contract):
    recording_id: Identifier
    sequence: int
    sha256: Digest
    durable: Literal[True] = True


class BatchRequest(Contract):
    recording_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    backend: Literal["quality", "synthetic", "local_vlm"] = "quality"
    hint: str = Field(default="", max_length=2000)
    model_path: str | None = None


class ReviewPatch(Contract):
    segment_id: Identifier
    expected_revision: int = Field(ge=0)
    decision: Literal["usable", "excluded", "unreviewed"]
    description: str | None = Field(default=None, max_length=4000)
    start_ns: int | None = Field(default=None, ge=0)
    end_ns: int | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=4000)


class DatasetSelection(Contract):
    processing_id: Identifier
    segment_ids: list[Identifier] = Field(min_length=1)


class DatasetRequest(Contract):
    name: str = Field(min_length=1, max_length=160)
    selections: list[DatasetSelection] = Field(min_length=1, max_length=1000)


class ExportRequest(Contract):
    format: Literal["hdf5", "egowam"] = "hdf5"
    fps: float = Field(default=10, gt=0, le=120)
    max_alignment_error_ms: float = Field(default=50, ge=0, le=1000)
