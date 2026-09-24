"""Small generated fixtures test adapter contracts; they are not real-data evidence."""

import base64
import json
from fractions import Fraction

import h5py
import numpy as np
import pytest

from capego.contracts import Packet, canonical
from capego.geometry import TrackingFrame
from capego.importers.egodex import SUFFIXES, EgoDexSource
from capego.storage import Store, StoreError

av = pytest.importorskip("av")
pytest.importorskip("scipy")


@pytest.fixture
def pair(tmp_path):
    video = tmp_path / "tiny.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("mpeg4", rate=30)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(6):
            pixels = np.full((48, 64, 3), 30 + i * 20, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    with h5py.File(video.with_suffix(".hdf5"), "w") as h5:
        h5.create_dataset("camera/intrinsic", data=[[40, 0, 32], [0, 40, 24], [0, 0, 1]])
        camera = np.tile(np.eye(4), (6, 1, 1))
        # Camera moves along source world x; local origin starts at x=10.
        camera[:, 0, 3] = 10 + np.arange(6) * 0.01
        h5.create_dataset("transforms/camera", data=camera)
        for side, sign in [("left", -1), ("right", 1)]:
            for suffix in SUFFIXES:
                matrix = np.tile(np.eye(4), (6, 1, 1))
                matrix[:, :3, 3] = [10 + sign * 0.2, 0.3, 0.5]
                h5.create_dataset("transforms/" + side + suffix, data=matrix)
                h5.create_dataset("confidences/" + side + suffix, data=np.ones(6))
        h5["confidences/leftHand"][2] = 0
        del h5["confidences/rightThumbTip"]
        h5.attrs["llm_description"] = "close lid"
        h5.attrs["llm_description2"] = "open lid"
        h5.attrs["which_llm_description"] = "2"
    return video


def test_camera_motion_reference_and_missing_confidence(pair):
    source = EgoDexSource(pair)
    first, second, hidden = (source.tracking(i) for i in (0, 1, 2))
    assert first.camera_pose == pytest.approx([0, 0, 0, 1, 0, 0, 0])
    assert second.camera_pose[0] == pytest.approx(0.01)
    assert second.hands["left"].joints[0] == pytest.approx([-0.2, 0.3, 0.5])
    assert second.hands_camera["left"].joints[0] == pytest.approx([-0.21, 0.3, 0.5])
    assert hidden.hands["left"].wrist_pose is None
    assert not hidden.hands["left"].wrist_valid
    assert first.hands["right"].joints[4] is None
    assert source.spec.calibration["dataset"]["description"] == "open lid"
    assert source.spec.origin == "dataset"
    assert [s.kind for s in source.spec.streams] == ["rgb", "tracking"]


def test_hard_reject_mismatched_frame_count(pair):
    with h5py.File(pair.with_suffix(".hdf5"), "a") as h5:
        del h5["transforms/leftHand"]
        h5.create_dataset("transforms/leftHand", data=np.tile(np.eye(4), (5, 1, 1)))
    with pytest.raises(ValueError, match="frame counts"):
        EgoDexSource(pair)


def test_packet_tracking_rejects_invalid_and_mismatched_fields(pair, tmp_path):
    source = EgoDexSource(pair)
    packets = list(source.packets())
    assert len(packets) == 12
    assert [p.timestamp_ns for p in packets[::2]] == source.times
    store = Store(tmp_path / "pc", min_free_bytes=0)
    store.create(source.spec)
    for packet in packets:
        store.receive(packet)
    original = packets[1]
    body = json.loads(original.payload())
    body["timestamp_ns"] += 1
    bad = original.model_copy(update={"payload_b64": base64.b64encode(canonical(body)).decode()})
    with pytest.raises(StoreError, match="timestamp"):
        Store.validate_payload(bad, source.spec)
    body = json.loads(original.payload())
    body["hands"]["left"]["wrist_pose"][3] = 2
    with pytest.raises(ValueError, match="normalized"):
        TrackingFrame.model_validate(body)
    body = json.loads(original.payload())
    body["hands"]["left"]["joint_valid"][0] = False
    with pytest.raises(ValueError, match="validity"):
        TrackingFrame.model_validate(body)
    with pytest.raises(ValueError):
        Packet.model_validate({**original.model_dump(), "codec": "untyped_json"})


def test_missing_confidences_stay_null(pair):
    with h5py.File(pair.with_suffix(".hdf5"), "a") as h5:
        del h5["confidences"]
    source = EgoDexSource(pair)
    frame = source.tracking(0)
    assert frame.camera_valid
    for hand in frame.hands.values():
        assert hand.confidence is None and hand.wrist_pose is None
        assert hand.joint_valid == [False] * 21 and hand.joints == [None] * 21
