"""Deterministic synthetic sensor source and recording replay; no camera hardware required."""

from __future__ import annotations

import base64
import heapq
import io
import math
import uuid

from PIL import Image, ImageDraw

from .contracts import Packet, RecordingSpec, Stream, canonical
from .storage import Store, utc_now


def synthetic_spec(recording_id=None, width=320, height=240, fps=10, imu_hz=100, chunk_seconds=1):
    return RecordingSpec(
        id=recording_id or f"rec-{uuid.uuid4().hex}",
        device_id="synthetic-rig",
        origin="synthetic",
        started_at=utc_now(),
        chunk_duration_ns=int(chunk_seconds * 1e9),
        streams=[
            Stream(id="left_rgb", kind="rgb", rate_hz=fps, width=width, height=height),
            Stream(id="right_rgb", kind="rgb", rate_hz=fps, width=width, height=height),
            Stream(id="imu", kind="imu", rate_hz=imu_hz),
        ],
        calibration={
            "status": "synthetic",
            "version": "synthetic-v1",
            "length_unit": "m",
            "reference_camera": "left_rgb",
            "baseline_m": 0.06,
            "camera_axes": "x_right_y_down_z_forward",
            "note": "Synthetic fixture, not physical calibration",
        },
    )


def synthetic_image(stream: Stream, timestamp_ns: int) -> bytes:
    width, height = stream.width, stream.height
    image = Image.new("RGB", (width, height), "#273947")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, height * 0.35, width, height), fill="#a3b4ba")
    draw.rectangle(
        (width * 0.58, height * 0.44, width * 0.88, height * 0.79),
        fill="#c8a779",
        outline="#675d4c",
        width=3,
    )
    t = timestamp_ns / 1e9
    x = width * (0.3 + 0.12 * math.sin(t)) + (-6 if stream.id == "right_rgb" else 0)
    y = height * 0.55
    draw.ellipse(
        (x - width * 0.06, y - height * 0.12, x + width * 0.06, y + height * 0.12),
        fill="#dc754f",
        outline="#833d2f",
        width=2,
    )
    for hx in [width * 0.2, x]:
        draw.line(
            (hx, height, hx + width * 0.05, height * 0.65),
            fill="#e1b99c",
            width=max(3, int(width * 0.045)),
        )
    draw.text((10, 8), "SYNTHETIC / CapEgo", fill="white")
    draw.text((10, 24), f"{stream.id}  {t:.3f}s", fill="white")
    output = io.BytesIO()
    image.save(output, "JPEG", quality=90)
    return output.getvalue()


def synthetic_packets(spec: RecordingSpec, duration_seconds: float):
    if spec.origin != "synthetic" or duration_seconds <= 0:
        raise ValueError("Synthetic source requires synthetic origin and positive duration")
    queue = [(0, i, 0) for i in range(len(spec.streams))]
    heapq.heapify(queue)
    sequence = 0
    stop_ns = round(duration_seconds * 1e9)
    while queue:
        timestamp_ns, index, sample = heapq.heappop(queue)
        if timestamp_ns >= stop_ns:
            break
        stream = spec.streams[index]
        if stream.kind == "rgb":
            codec, payload = "jpeg", synthetic_image(stream, timestamp_ns)
        else:
            codec = "imu_json"
            payload = canonical(
                {
                    "accel_m_s2": [0.0, 0.0, 9.80665],
                    "gyro_rad_s": [0.0, 0.02 * math.sin(timestamp_ns / 1e9), 0.0],
                }
            )
        yield Packet(
            recording_id=spec.id,
            sequence=sequence,
            stream_id=stream.id,
            timestamp_ns=timestamp_ns,
            source_timestamp_ns=timestamp_ns,
            clock_id="synthetic_clock",
            codec=codec,
            payload_b64=base64.b64encode(payload).decode(),
        )
        sequence += 1
        next_sample = sample + 1
        heapq.heappush(queue, (round(next_sample * 1e9 / stream.rate_hz), index, next_sample))


def replay_packets(store: Store, source_id: str, new_id: str):
    store.require_complete(source_id)
    for index, row in enumerate(store.packet_rows(source_id)):
        packet = store.read_packet(row)
        yield packet.model_copy(update={"recording_id": new_id, "sequence": index})
