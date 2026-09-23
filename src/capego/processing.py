"""Explicit per-recording processing jobs, immutable outputs and review history."""

from __future__ import annotations

import copy
import io
import json
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from .annotations import AnnotationSet
from .contracts import BatchRequest, ReviewPatch, canonical, sha256
from .storage import Store, StoreError, atomic_write, safe_id, utc_now


def read_result(store: Store, processing_id: str) -> dict:
    safe_id(processing_id)
    with store.connection() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (processing_id,)).fetchone()
    if not row:
        raise StoreError("not_found", "Processing job not found", 404)
    value = dict(row)
    value["config"] = json.loads(value["config"])
    value["result"] = json.loads(value["result"]) if value["result"] else None
    if value["result"]:
        path = store.root / "processing" / processing_id / "result.json"
        if not path.is_file() or path.read_bytes() != canonical(value["result"]):
            raise StoreError("result_corrupt", "Processing result does not match its immutable index")
    return value


def list_jobs(store: Store, limit=100, offset=0):
    with store.connection() as db:
        rows = db.execute("SELECT id,recording_id,batch_id,status,error,created_at FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return {"items": [dict(r) for r in rows], "total": total}


def quality_report(store, rec, rows):
    streams, flags = {}, []
    duration = rec["end"]["ended_at_ns"]
    for spec in rec["spec"]["streams"]:
        samples = [r for r in rows if r["stream_id"] == spec["id"]]
        times = np.array([r["timestamp_ns"] for r in samples], dtype=np.int64)
        period = 1e9 / spec["rate_hz"]
        gaps = []
        if len(times):
            gaps = [[int(a), int(b)] for a, b in zip(times[:-1], times[1:], strict=True) if b - a > period * 1.75]
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
                image_metrics.append({"timestamp_ns": row["timestamp_ns"], "mean": mean, "contrast": contrast,
                                      "valid": 5 < mean < 250 and contrast > 2})
            if any(not m["valid"] for m in image_metrics):
                flags.append(f"{spec['id']}:exposure_or_low_contrast")
        streams[spec["id"]] = {"samples": len(samples), "gaps": gaps, "image_metrics": image_metrics}
    rgb = [s for s in rec["spec"]["streams"] if s["kind"] == "rgb"]
    sync = None
    if len(rgb) >= 2:
        left = np.array([r["timestamp_ns"] for r in rows if r["stream_id"] == rgb[0]["id"]], dtype=np.int64)
        right = np.array([r["timestamp_ns"] for r in rows if r["stream_id"] == rgb[1]["id"]], dtype=np.int64)
        if len(left) and len(right):
            indices = np.searchsorted(right, left).clip(0, len(right)-1)
            errors = np.minimum(abs(left-right[indices]), abs(left-right[(indices-1).clip(0)]))
            sync = {"max_timestamp_difference_ns": int(errors.max()), "tolerance_ns": 2_000_000,
                    "hardware_sync_verified": False}
            if errors.max() > 2_000_000:
                flags.append("stereo:timestamp_misalignment")
    if duration <= 0 or not rows:
        flags.append("recording:empty")
    if rec["end"]["reason"] not in {"user", "source_exhausted"}:
        flags.append(f"recording:ended_{rec['end']['reason']}")
    return {"status": "pass" if not flags else "needs_review", "flags": flags, "streams": streams, "stereo": sync,
            "method": "timestamp gaps and basic exposure/contrast; not a hardware synchronization measurement"}


def synthetic_annotations(rec, times):
    duration = rec["end"]["ended_at_ns"]
    return AnnotationSet.model_validate({
        "tasks": [{"id": "task-1", "start_ns": 0, "end_ns": duration, "description": "合成桌面操作测试", "needs_review": False}],
        "operations": [{"id": "operation-1", "task_id": "task-1", "start_ns": 0, "end_ns": duration,
                        "description": "合成右手移动杯子，左手位于桌面", "hands": ["right"], "object_ids": ["object-cup"],
                        "action_label": "move", "observation_status": "observed", "needs_review": False}],
        "objects": [{"id": "object-cup", "name": "synthetic cup", "view": "left_rgb", "boxes": [
            {"timestamp_ns": t, "xyxy": [.24 + .12*math.sin(t/1e9), .43, .36+.12*math.sin(t/1e9), .67]} for t in times]}],
    })


def synthetic_geometry(times):
    frames = []
    for t in times:
        seconds = t / 1e9
        hands = {}
        for side, sign in [("left", -1), ("right", 1)]:
            wrist = [sign * .18 + .04*math.sin(seconds), .1, .5]
            joints = [wrist] + [[wrist[0] + (finger-2)*.012, wrist[1] - joint*.018,
                                wrist[2] + .003*math.sin(seconds+finger)] for finger in range(5) for joint in range(1, 5)]
            hands[side] = {"wrist_pose": wrist + [1., 0., 0., 0.], "wrist_valid": True,
                           "joints": joints, "joint_valid": [True]*21, "confidence": 1.0}
        frames.append({"timestamp_ns": t, "camera_pose": [0., 0., 0., 1., 0., 0., 0.], "camera_valid": True, "hands": hands})
    return {"status": "synthetic", "frame": "recording_local", "reference_camera": "left_rgb",
            "axes": "x_right_y_down_z_forward", "length_unit": "m", "quaternion_order": "wxyz",
            "pose_direction": "local_from_body", "provider": "synthetic-fixture-v1", "frames": frames,
            "note": "Synthetic numerical fixtures, not measurements or a hand-estimation model"}


class Processor:
    def __init__(self, store: Store, workers=1):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="capego-process")
        self.futures = {}
        self.lock = threading.Lock()

    def submit(self, request: BatchRequest):
        batch_id = f"batch-{uuid.uuid4().hex}"
        jobs = []
        for recording_id in dict.fromkeys(request.recording_ids):
            # Each recording is independent: a bad input does not reject the batch.
            try:
                self.store.require_complete(recording_id)
            except StoreError as exc:
                jobs.append({"recording_id": recording_id, "status": "rejected", "error": exc.message})
                continue
            jid = f"proc-{uuid.uuid4().hex}"
            with self.store.connection(write=True) as db:
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,NULL,NULL,?)", (jid, recording_id, batch_id, "queued", canonical(request.model_dump()).decode(), utc_now()))
            with self.lock:
                self.futures[jid] = self.pool.submit(self._run, jid)
            jobs.append({"id": jid, "recording_id": recording_id, "status": "queued"})
        return {"batch_id": batch_id, "jobs": jobs}

    def _run(self, jid):
        try:
            job = read_result(self.store, jid)
            with self.store.connection(write=True) as db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
            rec = self.store.require_complete(job["recording_id"])
            rows = self.store.packet_rows(rec["id"])
            quality = quality_report(self.store, rec, rows)
            duration = rec["end"]["ended_at_ns"]
            if duration <= 0:
                raise ValueError("Cannot annotate an empty recording")
            rgb_ids = [s["id"] for s in rec["spec"]["streams"] if s["kind"] == "rgb"]
            times = [r["timestamp_ns"] for r in rows if rgb_ids and r["stream_id"] == rgb_ids[0]]
            geometry = {"status": "missing", "provider": None, "frames": [], "reason": "No metric geometry backend configured"}
            backend = job["config"]["backend"]
            if backend == "synthetic":
                if rec["spec"]["origin"] != "synthetic":
                    raise ValueError("Synthetic annotations are restricted to synthetic recordings")
                annotations = synthetic_annotations(rec, times)
                geometry = synthetic_geometry(times)
            elif backend == "local_vlm":
                from .vlm import annotate_local
                annotations = annotate_local(self.store, rec, rows, job["config"])
            else:
                annotations = AnnotationSet.model_validate({"tasks": [{"id": "task-1", "start_ns": 0, "end_ns": duration,
                    "description": "待检查：尚未运行语义标注模型", "needs_review": True}], "operations": [], "objects": []})
            annotations.validate_duration(duration, rgb_ids)
            result = {"schema_version": 1, "id": jid, "recording_id": rec["id"], "created_at": utc_now(),
                      "source_sha256": rec["end"]["content_sha256"], "origin": rec["spec"]["origin"],
                      "backend": backend, "quality": quality, "annotations": annotations.model_dump(), "geometry": geometry}
            body = canonical(result)
            atomic_write(self.store.root / "processing" / jid / "result.json", body)
            with self.store.connection(write=True) as db:
                db.execute("UPDATE jobs SET status='succeeded',result=? WHERE id=?", (body.decode(), jid))
        except Exception as exc:
            with self.store.connection(write=True) as db:
                db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (f"{type(exc).__name__}: {exc}", jid))

    def wait(self, jid, timeout=120):
        with self.lock:
            future = self.futures.get(jid)
        if future:
            future.result(timeout=timeout)
        return read_result(self.store, jid)

    def close(self):
        self.pool.shutdown(wait=True)


def effective_annotations(store, jid):
    job = read_result(store, jid)
    if job["status"] != "succeeded":
        raise StoreError("not_ready", "Processing must succeed before review")
    annotations = copy.deepcopy(job["result"]["annotations"])
    with store.connection() as db:
        reviews = db.execute("SELECT segment_id,revision,body FROM reviews WHERE processing_id=? ORDER BY revision", (jid,)).fetchall()
    latest = {r["segment_id"]: r for r in reviews}
    for span in [*annotations["tasks"], *annotations["operations"]]:
        span["review"] = {"revision": 0, "decision": "unreviewed", "note": ""}
        if span["id"] in latest:
            r = latest[span["id"]]
            patch = json.loads(r["body"])
            for k in ("description", "start_ns", "end_ns"):
                if patch.get(k) is not None:
                    span[k] = patch[k]
            span["review"] = {"revision": r["revision"], "decision": patch["decision"], "note": patch["note"]}
    return annotations


def save_review(store, jid, patch: ReviewPatch):
    annotations = effective_annotations(store, jid)
    span = next((s for s in [*annotations["tasks"], *annotations["operations"]] if s["id"] == patch.segment_id), None)
    if not span:
        raise StoreError("not_found", "Segment not found", 404)
    # Validate the resulting hierarchy before persisting; boundaries cannot orphan operations.
    candidate = copy.deepcopy(annotations)
    for item in [*candidate["tasks"], *candidate["operations"]]:
        item.pop("review", None)
        if item["id"] == patch.segment_id:
            item.update({k: v for k, v in patch.model_dump().items() if k in {"description", "start_ns", "end_ns"} and v is not None})
    try:
        rec = store.recording(read_result(store, jid)["recording_id"])
        AnnotationSet.model_validate(candidate).validate_duration(rec["end"]["ended_at_ns"], [s["id"] for s in rec["spec"]["streams"] if s["kind"] == "rgb"])
    except ValueError as exc:
        raise StoreError("invalid_annotation", str(exc), 422) from exc
    with store.connection(write=True) as db:
        revision = db.execute("SELECT COALESCE(MAX(revision),0) FROM reviews WHERE processing_id=? AND segment_id=?", (jid, patch.segment_id)).fetchone()[0]
        if revision != patch.expected_revision:
            raise StoreError("revision_conflict", "Review changed; refresh before saving")
        body = patch.model_dump()
        # Every revision stores effective fields, so changing only the decision never
        # silently reverts an earlier description or interval correction.
        for key in ("description", "start_ns", "end_ns"):
            if body[key] is None:
                body[key] = span[key]
        db.execute("INSERT INTO reviews VALUES (?,?,?,?,?)", (jid, patch.segment_id, revision+1, canonical(body).decode(), utc_now()))
    return {"processing_id": jid, "segment_id": patch.segment_id, "revision": revision+1, "decision": patch.decision}


def result_digest(result):
    return sha256(canonical(result))
