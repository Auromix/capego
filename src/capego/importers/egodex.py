"""Read paired EgoDex video/ARKit estimates without fabricating sensor streams.

No upstream sample code is vendored. Camera transforms follow EgoDex's released
projection convention (inverse(camera) @ joint, directly projected with K).
The local reference is the first camera; body orientation axes stay source-native.
"""

from __future__ import annotations

import base64
import hashlib
import io
import uuid
from pathlib import Path

import h5py
import numpy as np

from ..contracts import Packet, RecordingSpec, Stream, canonical
from ..geometry import JOINT_NAMES, TrackingFrame
from ..storage import utc_now

SOURCE_URL = "https://github.com/apple-aiml-research/ml-egodex"
SUFFIXES = ["Hand", "ThumbKnuckle", "ThumbIntermediateBase", "ThumbIntermediateTip", "ThumbTip"] + [
    finger + "Finger" + joint
    for finger in ("Index", "Middle", "Ring", "Little")
    for joint in ("Knuckle", "IntermediateBase", "IntermediateTip", "Tip")
]


def file_digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def rigid(matrix):
    return (
        matrix.shape == (4, 4)
        and np.isfinite(matrix).all()
        and np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-5)
        and np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-3)
        and abs(np.linalg.det(matrix[:3, :3]) - 1) < 1e-3
    )


def pose(matrix):
    from scipy.spatial.transform import Rotation

    q = Rotation.from_matrix(matrix[:3, :3]).as_quat()  # xyzw -> wxyz
    return matrix[:3, 3].tolist() + [float(q[3]), *q[:3].tolist()]


class EgoDexSource:
    """Preflight a complete pair before opening a recording. Optional capego[data]."""

    def __init__(self, video, *, recording_id=None, confidence_threshold=0.5):
        import av

        self.video = Path(video)
        self.annotations = self.video.with_suffix(".hdf5")
        if not 0 < confidence_threshold <= 1:
            raise ValueError("Confidence threshold must be in (0, 1]")
        self.threshold = confidence_threshold
        self.times = []
        with av.open(str(self.video)) as container:
            stream = container.streams.video[0]
            width, height, rate = stream.width, stream.height, float(stream.average_rate)
            for frame in container.decode(video=0):
                if frame.pts is None or frame.time_base is None:
                    raise ValueError("Video is missing presentation timestamps")
                self.times.append(round(frame.pts * frame.time_base * 1_000_000_000))
        if len(self.times) < 2 or any(
            b <= a for a, b in zip(self.times[:-1], self.times[1:], strict=True)
        ):
            raise ValueError("Video requires at least two strictly increasing timestamps")
        if self.times[0] < 0 or abs(rate - 30) > 0.01:
            raise ValueError("This EgoDex adapter expects nonnegative 30 Hz video PTS")
        if not np.allclose(np.diff(self.times), 1e9 / 30, atol=1_000_000):
            raise ValueError("Video timing differs from EgoDex's frame-index annotation clock")
        with h5py.File(self.annotations) as h5:
            self.transforms = {
                k: np.asarray(v, dtype=np.float64) for k, v in h5["transforms"].items()
            }
            if any(v.shape != (len(self.times), 4, 4) for v in self.transforms.values()):
                raise ValueError("Video and annotation frame counts/shapes differ")
            self.confidences = {k: np.asarray(v) for k, v in h5.get("confidences", {}).items()}
            if any(v.shape != (len(self.times),) for v in self.confidences.values()):
                raise ValueError("Confidence frame count differs from video")
            camera = self.transforms["camera"][0]
            if not rigid(camera):
                raise ValueError("First camera transform is not a valid local reference")
            self.local_from_world = np.linalg.inv(camera)
            intrinsic = np.asarray(h5["camera/intrinsic"])
            if intrinsic.shape != (3, 3) or not np.isfinite(intrinsic).all():
                raise ValueError("Invalid camera intrinsic matrix")
            which = str(h5.attrs.get("which_llm_description", "1"))
            description = str(
                h5.attrs.get("llm_description2" if which == "2" else "llm_description", "")
            )
        self.duration_ns = self.times[-1] - self.times[0] + round(1e9 / rate)
        metadata = {
            "provider": "egodex-arkit-provided-v1",
            "source_url": SOURCE_URL,
            "sample": "/".join(self.video.parts[-3:]),
            "license": "CC-BY-NC-ND (see upstream dataset terms)",
            "files_sha256": {
                self.video.name: file_digest(self.video),
                self.annotations.name: file_digest(self.annotations),
            },
            "description": description,
            "description_source": "EgoDex provided LLM/VLM annotation; requires review",
            "confidence_threshold": self.threshold,
            "missing_confidence": "invalid",
            "geometry": {
                "status": "estimated",
                "frame": "recording_local",
                "reference_camera": "rgb",
                "axes": "x_right_y_down_z_forward",
                "length_unit": "m",
                "quaternion_order": "wxyz",
                "pose_direction": "local_from_body",
                "body_axes": "EgoDex source-native",
                "provider": "egodex-arkit-provided-v1",
                "hand_reference": "wrist",
                "joint_names": JOINT_NAMES,
                "source_joint_names": SUFFIXES,
                "local_from_source_world": self.local_from_world.tolist(),
                "note": "Provided ARKit estimates; not CapEgo predictions or robot action ground truth",
            },
        }
        self.spec = RecordingSpec(
            id=recording_id or f"egodex-{uuid.uuid4().hex[:16]}",
            device_id="egodex-replay",
            origin="dataset",
            started_at=utc_now(),
            streams=[
                Stream(id="rgb", kind="rgb", rate_hz=rate, width=width, height=height),
                Stream(id="tracking", kind="tracking", rate_hz=rate),
            ],
            calibration={
                "reference_camera": "rgb",
                "intrinsic": intrinsic.tolist(),
                "dataset": metadata,
            },
            clock={
                "unit": "ns",
                "reference": "recording_start",
                "source": "video_pts",
                "first_source_timestamp_ns": self.times[0],
                "annotation_alignment": "EgoDex frame index, 30 Hz",
                "hardware_sync_verified": False,
                "rgb_encoding": "decoded MP4 to JPEG quality 95; source hashes retained",
            },
        )

    def confidence(self, name, index):
        values = self.confidences.get(name)
        value = float(values[index]) if values is not None else None
        return value if value is not None and np.isfinite(value) and 0 <= value <= 1 else None

    def hand(self, side, index, reference_from_world, camera_valid):
        joints, masks = [], []
        wrist_pose = None
        for suffix in SUFFIXES:
            name = side + suffix
            matrices = self.transforms.get(name)
            confidence = self.confidence(name, index)
            valid = (
                camera_valid
                and matrices is not None
                and confidence is not None
                and confidence >= self.threshold
                and rigid(matrices[index])
            )
            transformed = reference_from_world @ matrices[index] if valid else None
            joints.append(transformed[:3, 3].tolist() if valid else None)
            masks.append(bool(valid))
            if suffix == "Hand" and valid:
                wrist_pose = pose(transformed)
        return {
            "wrist_pose": wrist_pose,
            "wrist_valid": wrist_pose is not None,
            "joints": joints,
            "joint_valid": masks,
            "confidence": self.confidence(side + "Hand", index),
        }

    def tracking(self, index):
        camera = self.transforms["camera"][index]
        valid = rigid(camera)
        camera_from_world = np.linalg.inv(camera) if valid else np.eye(4)
        return TrackingFrame.model_validate(
            {
                "timestamp_ns": self.times[index] - self.times[0],
                "camera_valid": bool(valid),
                "camera_pose": pose(self.local_from_world @ camera) if valid else None,
                "hands": {
                    s: self.hand(s, index, self.local_from_world, valid) for s in ("left", "right")
                },
                "hands_camera": {
                    s: self.hand(s, index, camera_from_world, valid) for s in ("left", "right")
                },
            }
        )

    def packets(self):
        import av

        count = 0
        with av.open(str(self.video)) as container:
            for index, frame in enumerate(container.decode(video=0)):
                if (
                    index >= len(self.times)
                    or round(frame.pts * frame.time_base * 1_000_000_000) != self.times[index]
                ):
                    raise ValueError("Video changed after preflight")
                encoded = io.BytesIO()
                frame.to_image().save(encoded, "JPEG", quality=95)
                for offset, (stream, codec, body) in enumerate(
                    [
                        ("rgb", "jpeg", encoded.getvalue()),
                        ("tracking", "tracking_json", canonical(self.tracking(index).model_dump())),
                    ]
                ):
                    yield Packet(
                        recording_id=self.spec.id,
                        sequence=index * 2 + offset,
                        stream_id=stream,
                        timestamp_ns=self.times[index] - self.times[0],
                        source_timestamp_ns=self.times[index],
                        clock_id="egodex_video_pts",
                        codec=codec,
                        payload_b64=base64.b64encode(body).decode(),
                    )
                count += 1
        if count != len(self.times):
            raise ValueError("Video truncated after preflight")
