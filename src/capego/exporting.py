"""Native archival HDF5 and strict, provenance-preserving EgoWAM episode export."""
from __future__ import annotations

import io
import json
import os
import uuid

import h5py
import numpy as np
from PIL import Image

from .contracts import ExportRequest, canonical, sha256
from .datasets import get_dataset, validate_sources
from .processing import read_result
from .storage import StoreError, atomic_write, fsync_dir, safe_id

EGOWAM_COMMIT = "c87617fe37a6ed6a951e6b176ad552200c425c93"


def nearest(times, targets, tolerance_ns):
    times, targets = np.asarray(times, dtype=np.int64), np.asarray(targets, dtype=np.int64)
    if not len(times):
        return np.zeros(len(targets), dtype=np.int64), np.zeros(len(targets), dtype=bool)
    upper = np.searchsorted(times, targets).clip(0, len(times)-1)
    lower = (upper-1).clip(0)
    indices = np.where(abs(times[lower]-targets) <= abs(times[upper]-targets), lower, upper)
    return indices, abs(times[indices]-targets) <= tolerance_ns


def write_hdf5(store, dataset, output):
    with h5py.File(output / "dataset.h5", "w") as file:
        file.attrs["schema"] = "capego.native.v1"
        file.create_dataset("manifest_json", data=canonical(dataset).decode(), dtype=h5py.string_dtype())
        for i, item in enumerate(dataset["items"]):
            group = file.create_group(f"segments/{i:06d}")
            rec = store.recording(item["recording_id"])
            result = read_result(store, item["processing_id"])["result"]
            begin, end = item["segment"]["start_ns"], item["segment"]["end_ns"]
            geometry = {**result["geometry"], "frames": [f for f in result["geometry"]["frames"] if begin <= f["timestamp_ns"] < end]}
            for key, value in {"calibration": rec["spec"]["calibration"], "clock": rec["spec"]["clock"],
                               "annotations": item["annotations"], "quality": result["quality"], "geometry": geometry}.items():
                group.create_dataset(f"{key}_json", data=canonical(value).decode(), dtype=h5py.string_dtype())
            begin, end = item["segment"]["start_ns"], item["segment"]["end_ns"]
            for stream in rec["spec"]["streams"]:
                rows = [r for r in store.packet_rows(rec["id"]) if r["stream_id"] == stream["id"] and begin <= r["timestamp_ns"] < end]
                packets = [store.read_packet(r) for r in rows]
                sg = group.create_group(stream["id"])
                sg.attrs["stream_json"] = canonical(stream).decode()
                for key in ("timestamp_ns", "source_timestamp_ns", "sequence"):
                    sg.create_dataset(key, data=np.array([getattr(p, key) for p in packets], dtype=np.int64))
                sg.create_dataset("clock_id", data=np.array([p.clock_id for p in packets], dtype=h5py.string_dtype()))
                if stream["kind"] == "rgb":
                    payloads = sg.create_dataset("encoded_image", shape=(len(packets),), dtype=h5py.vlen_dtype(np.dtype("uint8")))
                    for j, packet in enumerate(packets):
                        payloads[j] = np.frombuffer(packet.payload(), dtype=np.uint8)
                    sg.create_dataset("codec", data=np.array([p.codec for p in packets], dtype=h5py.string_dtype()))
                else:
                    values = [json.loads(p.payload()) for p in packets]
                    for key in ("accel_m_s2", "gyro_rad_s"):
                        sg.create_dataset(key, data=np.array([v[key] for v in values], dtype=np.float64).reshape(-1, 3))
        file.flush()
    with open(output / "dataset.h5", "rb") as file:
        os.fsync(file.fileno())
    return {"files": ["dataset.h5"], "segments": len(dataset["items"]), "format": "capego.native.v1"}


def write_egowam(store, dataset, output, config):
    try:
        import zarr
        from zarr.core.dtype import VariableLengthBytes
    except ImportError as exc:
        raise StoreError("export_dependencies_missing", "Install capego[export] for EgoWAM export", 422) from exc
    episodes, filtered = [], []
    for item in dataset["items"]:
        rec = store.recording(item["recording_id"])
        geometry = read_result(store, item["processing_id"])["result"]["geometry"]
        if geometry["status"] == "missing" or not geometry["frames"]:
            filtered.append({"processing_id": item["processing_id"], "reason": "metric_geometry_missing"})
            continue
        if any(geometry.get(k) != v for k, v in {"axes": "x_right_y_down_z_forward", "pose_direction": "local_from_body", "quaternion_order": "wxyz", "length_unit": "m"}.items()):
            raise StoreError("unsupported_geometry", "Geometry requires an explicit coordinate adapter", 422)
        begin, end = item["segment"]["start_ns"], item["segment"]["end_ns"]
        targets = np.arange(begin, end, round(1e9 / config.fps), dtype=np.int64)
        reference = geometry["reference_camera"]
        rows = [r for r in store.packet_rows(rec["id"]) if r["stream_id"] == reference and begin <= r["timestamp_ns"] < end]
        frames = [f for f in geometry["frames"] if begin <= f["timestamp_ns"] < end]
        tolerance = config.max_alignment_error_ms * 1e6
        ri, valid_rgb = nearest([r["timestamp_ns"] for r in rows], targets, tolerance)
        gi, valid_geometry = nearest([f["timestamp_ns"] for f in frames], targets, tolerance)
        valid = valid_rgb & valid_geometry
        for i in range(len(targets)):
            if valid[i]:
                f = frames[gi[i]]
                valid[i] = bool(f["camera_valid"] and all(f["hands"][side]["wrist_valid"] for side in ("left", "right")))
        valid_indices = np.flatnonzero(valid)
        runs = np.split(valid_indices, np.flatnonzero(np.diff(valid_indices) != 1)+1)
        for run in runs:
            if len(run) < 2:
                continue
            eid = f"episode_{len(episodes):06d}.zarr"
            group = zarr.open_group(str(output / eid), mode="w", zarr_format=3)
            selected = [frames[gi[i]] for i in run]
            numeric = {"obs_rgb_timestamps_ns": targets[run],
                       "obs_head_pose": np.asarray([f["camera_pose"] for f in selected], dtype=np.float32),
                       **{f"{side}.obs_ee_pose": np.asarray([f["hands"][side]["wrist_pose"] for f in selected], dtype=np.float32) for side in ("left", "right")}}
            features = {}
            for key, array in numeric.items():
                if not np.isfinite(array).all():
                    raise ValueError("Non-finite training target")
                if array.ndim == 2 and array.shape[-1] == 7 and not np.allclose(np.linalg.norm(array[:, 3:], axis=-1), 1, atol=1e-3):
                    raise ValueError("Pose quaternion must be normalized")
                group.create_array(key, data=array, chunks=(min(len(run), 128), *array.shape[1:]))
                features[key] = {"dtype": str(array.dtype), "shape": list(array.shape[1:])}
            image_rows = [rows[ri[i]] for i in run]
            images = group.create_array("images.front_1", shape=(len(run),), chunks=(1,), dtype=VariableLengthBytes())
            for j, row in enumerate(image_rows):
                packet = store.read_packet(row)
                payload = packet.payload()
                if packet.codec != "jpeg":
                    with Image.open(io.BytesIO(payload)) as image:
                        encoded = io.BytesIO()
                        image.convert("RGB").save(encoded, "JPEG", quality=95)
                        payload = encoded.getvalue()
                images[j:j+1] = np.array([payload], dtype=object)
            stream = next(s for s in rec["spec"]["streams"] if s["id"] == reference)
            features["images.front_1"] = {"dtype": "jpeg", "shape": [stream["height"], stream["width"], 3], "names": ["height", "width", "channel"]}
            annotations = group.create_array("annotations", shape=(1,), chunks=(1,), dtype=VariableLengthBytes())
            annotations[:] = np.array([canonical({"text": item["segment"]["description"], "start_idx": 0, "end_idx": len(run)-1})], dtype=object)
            features["annotations"] = {"dtype": "json", "shape": [1], "format": "annotation_v1"}
            group.attrs.update({"total_frames": len(run), "fps": config.fps, "embodiment": "aria_bimanual", "features": features,
                "capego": {"dataset_sha256": dataset["sha256"], "source": item, "geometry_provider": geometry["provider"],
                           "reference": "Camera pose as reference pose; wrist trajectory as human action proxy",
                           "actual_embodiment": "capego_ego", "origin": item["origin"], "upstream_commit": EGOWAM_COMMIT}})
            episodes.append({"path": eid, "frames": len(run), "recording_id": rec["id"], "source_sequences": [r["sequence"] for r in image_rows],
                             "start_ns": int(targets[run[0]]), "end_ns": int(targets[run[-1]])})
        if not valid.all():
            filtered.append({"processing_id": item["processing_id"], "reason": "missing_or_unaligned_frames", "frames": int((~valid).sum())})
    if not episodes:
        raise StoreError("no_training_samples", "No consecutive RGB + both wrist poses + camera poses; review cannot fill missing geometry", 422)
    return {"format": "egowam.human.zarr", "upstream_commit": EGOWAM_COMMIT, "episodes": episodes, "filtered": filtered,
            "validation": "exported; run upstream validation separately", "masks": "invalid windows filtered, not filled"}


def export_dataset(store, dataset_id, config: ExportRequest):
    dataset = get_dataset(store, dataset_id)
    validate_sources(store, dataset)
    export_id = f"export-{uuid.uuid4().hex}"
    output = store.root / "exports" / export_id
    output.mkdir(parents=True, exist_ok=False)
    try:
        report = write_hdf5(store, dataset, output) if config.format == "hdf5" else write_egowam(store, dataset, output, config)
        report.update({"id": export_id, "dataset_id": dataset_id, "dataset_sha256": dataset["sha256"], "config": config.model_dump(),
                       "origins": sorted({i["origin"] for i in dataset["items"]})})
        report["content_files"] = {str(p.relative_to(output)): sha256(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()}
        atomic_write(output / "report.json", canonical(report))
        fsync_dir(output.parent)
        return report
    except Exception:
        atomic_write(output / "FAILED", b"Incomplete export; do not train from this directory.\n")
        raise


def read_export(store, export_id):
    path = store.root / "exports" / safe_id(export_id) / "report.json"
    if not path.is_file():
        raise StoreError("not_found", "Completed export not found", 404)
    return json.loads(path.read_bytes())
