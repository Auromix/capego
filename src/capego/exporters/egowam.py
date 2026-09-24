"""EgoWAM Human loader adapter; wrist motion is an ego action proxy."""

import io

import numpy as np
from PIL import Image

from ..contracts import canonical
from ..processing import read_result
from ..storage import StoreError
from .alignment import nearest

EGOWAM_COMMIT = "c87617fe37a6ed6a951e6b176ad552200c425c93"


def write_egowam(store, dataset, output, config):
    try:
        import zarr
        from zarr.core.dtype import VariableLengthBytes
    except ImportError as exc:
        raise StoreError(
            "export_dependencies_missing", "Install capego[export] for EgoWAM export", 422
        ) from exc
    episodes, filtered = [], []
    for item in dataset["items"]:
        rec = store.recording(item["recording_id"])
        geometry = read_result(store, item["processing_id"])["result"]["geometry"]
        if geometry["status"] == "missing" or not geometry["frames"]:
            filtered.append(
                {"processing_id": item["processing_id"], "reason": "metric_geometry_missing"}
            )
            continue
        if any(
            geometry.get(k) != v
            for k, v in {
                "axes": "x_right_y_down_z_forward",
                "pose_direction": "local_from_body",
                "quaternion_order": "wxyz",
                "length_unit": "m",
            }.items()
        ):
            raise StoreError(
                "unsupported_geometry", "Geometry requires an explicit coordinate adapter", 422
            )
        begin, end = item["segment"]["start_ns"], item["segment"]["end_ns"]
        targets = np.arange(begin, end, round(1e9 / config.fps), dtype=np.int64)
        reference = geometry["reference_camera"]
        rows = [
            r
            for r in store.packet_rows(rec["id"])
            if r["stream_id"] == reference and begin <= r["timestamp_ns"] < end
        ]
        frames = [f for f in geometry["frames"] if begin <= f["timestamp_ns"] < end]
        tolerance = config.max_alignment_error_ms * 1e6
        ri, valid_rgb = nearest([r["timestamp_ns"] for r in rows], targets, tolerance)
        gi, valid_geometry = nearest([f["timestamp_ns"] for f in frames], targets, tolerance)
        valid = valid_rgb & valid_geometry
        for i in range(len(targets)):
            if valid[i]:
                f = frames[gi[i]]
                valid[i] = bool(
                    f["camera_valid"]
                    and all(f["hands"][side]["wrist_valid"] for side in ("left", "right"))
                )
        valid_indices = np.flatnonzero(valid)
        runs = np.split(valid_indices, np.flatnonzero(np.diff(valid_indices) != 1) + 1)
        for run in runs:
            if len(run) < 2:
                continue
            eid = f"episode_{len(episodes):06d}.zarr"
            group = zarr.open_group(str(output / eid), mode="w", zarr_format=3)
            selected = [frames[gi[i]] for i in run]
            numeric = {
                "obs_rgb_timestamps_ns": targets[run],
                "capego_source_rgb_timestamps_ns": np.asarray(
                    [rows[ri[i]]["timestamp_ns"] for i in run], dtype=np.int64
                ),
                "capego_source_geometry_timestamps_ns": np.asarray(
                    [frames[gi[i]]["timestamp_ns"] for i in run], dtype=np.int64
                ),
                "obs_head_pose": np.asarray([f["camera_pose"] for f in selected], dtype=np.float32),
                **{
                    f"{side}.obs_ee_pose": np.asarray(
                        [f["hands"][side]["wrist_pose"] for f in selected], dtype=np.float32
                    )
                    for side in ("left", "right")
                },
            }
            features = {}
            for key, array in numeric.items():
                if not np.isfinite(array).all():
                    raise ValueError("Non-finite training target")
                if (
                    array.ndim == 2
                    and array.shape[-1] == 7
                    and not np.allclose(np.linalg.norm(array[:, 3:], axis=-1), 1, atol=1e-3)
                ):
                    raise ValueError("Pose quaternion must be normalized")
                group.create_array(key, data=array, chunks=(min(len(run), 128), *array.shape[1:]))
                features[key] = {"dtype": str(array.dtype), "shape": list(array.shape[1:])}
            image_rows = [rows[ri[i]] for i in run]
            images = group.create_array(
                "images.front_1", shape=(len(run),), chunks=(1,), dtype=VariableLengthBytes()
            )
            for j, row in enumerate(image_rows):
                packet = store.read_packet(row)
                payload = packet.payload()
                if packet.codec != "jpeg":
                    with Image.open(io.BytesIO(payload)) as image:
                        encoded = io.BytesIO()
                        image.convert("RGB").save(encoded, "JPEG", quality=95)
                        payload = encoded.getvalue()
                images[j : j + 1] = np.array([payload], dtype=object)
            stream = next(s for s in rec["spec"]["streams"] if s["id"] == reference)
            features["images.front_1"] = {
                "dtype": "jpeg",
                "shape": [stream["height"], stream["width"], 3],
                "names": ["height", "width", "channel"],
            }
            annotations = group.create_array(
                "annotations", shape=(1,), chunks=(1,), dtype=VariableLengthBytes()
            )
            annotations[:] = np.array(
                [
                    canonical(
                        {
                            "text": item["segment"]["description"],
                            "start_idx": 0,
                            "end_idx": len(run) - 1,
                        }
                    )
                ],
                dtype=object,
            )
            features["annotations"] = {"dtype": "json", "shape": [1], "format": "annotation_v1"}
            group.attrs.update(
                {
                    "total_frames": len(run),
                    "fps": config.fps,
                    "embodiment": "aria_bimanual",
                    "features": features,
                    "capego": {
                        "dataset_sha256": dataset["sha256"],
                        "source": item,
                        "geometry_provider": geometry["provider"],
                        "calibration": rec["spec"]["calibration"],
                        "clock": rec["spec"]["clock"],
                        "geometry_convention": {k: v for k, v in geometry.items() if k != "frames"},
                        "alignment": {
                            "method": "bounded_nearest",
                            "interpolation": False,
                            "max_error_ms": config.max_alignment_error_ms,
                        },
                        "reference": "Camera pose as reference pose; wrist trajectory as human action proxy",
                        "actual_embodiment": "capego_ego",
                        "origin": item["origin"],
                        "upstream_commit": EGOWAM_COMMIT,
                    },
                }
            )
            episodes.append(
                {
                    "path": eid,
                    "frames": len(run),
                    "recording_id": rec["id"],
                    "source_sequences": [r["sequence"] for r in image_rows],
                    "start_ns": int(targets[run[0]]),
                    "end_ns": int(targets[run[-1]]),
                }
            )
        if not valid.all():
            filtered.append(
                {
                    "processing_id": item["processing_id"],
                    "reason": "missing_or_unaligned_frames",
                    "frames": int((~valid).sum()),
                }
            )
    if not episodes:
        raise StoreError(
            "no_training_samples",
            "No consecutive RGB + both wrist poses + camera poses; review cannot fill missing geometry",
            422,
        )
    return {
        "format": "egowam.human.zarr",
        "upstream_commit": EGOWAM_COMMIT,
        "episodes": episodes,
        "filtered": filtered,
        "validation": "exported; run upstream validation separately",
        "masks": "invalid windows filtered, not filled",
    }
