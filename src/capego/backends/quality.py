"""Sensor-independent quality checks on native sampling."""

import io

import numpy as np
from PIL import Image


def quality_report(store, rec, rows):
    streams, flags = {}, []
    duration = rec["end"]["ended_at_ns"]
    for spec in rec["spec"]["streams"]:
        samples = [r for r in rows if r["stream_id"] == spec["id"]]
        times = np.array([r["timestamp_ns"] for r in samples], dtype=np.int64)
        period = 1e9 / spec["rate_hz"]
        gaps = []
        if len(times):
            gaps = [
                [int(a), int(b)]
                for a, b in zip(times[:-1], times[1:], strict=True)
                if b - a > period * 1.75
            ]
            if times[0] > period * 1.75:
                gaps.insert(0, [0, int(times[0])])
            if duration - times[-1] > period * 1.75:
                gaps.append([int(times[-1]), duration])
        if not samples or gaps:
            flags.append(f"{spec['id']}:missing_or_gapped")
        image_metrics = []
        if spec["kind"] == "rgb":
            for row in samples:
                with Image.open(io.BytesIO(store.read_packet(row).payload())) as image:
                    gray = np.asarray(image.convert("L"), dtype=np.float32)
                mean = float(gray.mean())
                contrast = float(gray.std())
                image_metrics.append(
                    {
                        "timestamp_ns": row["timestamp_ns"],
                        "mean": mean,
                        "contrast": contrast,
                        "valid": 5 < mean < 250 and contrast > 2,
                    }
                )
            if any(not m["valid"] for m in image_metrics):
                flags.append(f"{spec['id']}:exposure_or_low_contrast")
        streams[spec["id"]] = {
            "samples": len(samples),
            "gaps": gaps,
            "image_metrics": image_metrics,
        }
    rgb = [s for s in rec["spec"]["streams"] if s["kind"] == "rgb"]
    sync = None
    if len(rgb) >= 2:
        left = np.array(
            [r["timestamp_ns"] for r in rows if r["stream_id"] == rgb[0]["id"]], dtype=np.int64
        )
        right = np.array(
            [r["timestamp_ns"] for r in rows if r["stream_id"] == rgb[1]["id"]], dtype=np.int64
        )
        if len(left) and len(right):
            indices = np.searchsorted(right, left).clip(0, len(right) - 1)
            errors = np.minimum(
                abs(left - right[indices]), abs(left - right[(indices - 1).clip(0)])
            )
            sync = {
                "max_timestamp_difference_ns": int(errors.max()),
                "tolerance_ns": 2_000_000,
                "hardware_sync_verified": False,
            }
            if errors.max() > 2_000_000:
                flags.append("stereo:timestamp_misalignment")
    if duration <= 0 or not rows:
        flags.append("recording:empty")
    if rec["end"]["reason"] not in {"user", "source_exhausted"}:
        flags.append(f"recording:ended_{rec['end']['reason']}")
    return {
        "status": "pass" if not flags else "needs_review",
        "flags": flags,
        "streams": streams,
        "stereo": sync,
        "method": "timestamp gaps and basic exposure/contrast; not a hardware synchronization measurement",
    }
