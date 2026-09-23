import json

import h5py
import pytest

from capego.annotations import AnnotationSet
from capego.contracts import (
    BatchRequest,
    DatasetRequest,
    EndRecording,
    ExportRequest,
    ReviewPatch,
    sequence_digest,
)
from capego.datasets import create_dataset, get_dataset
from capego.exporting import export_dataset
from capego.processing import Processor, effective_annotations, list_jobs, read_result, save_review
from capego.sources import synthetic_packets, synthetic_spec
from capego.storage import Store, StoreError


@pytest.fixture
def captured(tmp_path):
    store = Store(tmp_path, min_free_bytes=0)
    spec = synthetic_spec("recording", width=64, height=48, fps=10, imu_hz=20, chunk_seconds=.2)
    store.create(spec)
    packets = list(synthetic_packets(spec, 1))
    for p in packets:
        store.receive(p)
    store.end(spec.id, EndRecording(packet_count=len(packets), content_sha256=sequence_digest([(p.sequence, p.digest()) for p in packets]), ended_at_ns=1_000_000_000, reason="user"))
    return store, spec


def process(store, rid="recording", backend="synthetic"):
    processor = Processor(store)
    try:
        batch = processor.submit(BatchRequest(recording_ids=[rid], backend=backend))
        job = processor.wait(batch["jobs"][0]["id"])
        assert job["status"] == "succeeded", job
        return job
    finally:
        processor.close()


def selection(job, segment="task-1"):
    return DatasetRequest(name="test dataset", selections=[{"processing_id": job["id"], "segment_ids": [segment]}])


def test_arrival_never_processes_and_batch_is_independent(captured):
    store, spec = captured
    assert list_jobs(store)["total"] == 0
    incomplete = synthetic_spec("incomplete", width=64, height=48)
    store.create(incomplete)
    processor = Processor(store)
    try:
        batch = processor.submit(BatchRequest(recording_ids=["incomplete", spec.id, "missing"], backend="synthetic"))
        assert [j["status"] for j in batch["jobs"]] == ["rejected", "queued", "rejected"]
        job = processor.wait(batch["jobs"][1]["id"])
        assert job["status"] == "succeeded"
        assert job["result"]["quality"]["status"] == "pass"
        assert job["result"]["geometry"]["status"] == "synthetic"
        assert len(job["result"]["geometry"]["frames"][0]["hands"]["left"]["joints"]) == 21
    finally:
        processor.close()


def test_review_snapshot_and_reprocess_are_independent(captured):
    store, spec = captured
    job = process(store)
    dataset = create_dataset(store, selection(job))
    save_review(store, job["id"], ReviewPatch(segment_id="task-1", expected_revision=0, decision="usable", description="Revised description"))
    assert get_dataset(store, dataset["id"])["sha256"] == dataset["sha256"]
    assert get_dataset(store, dataset["id"])["items"][0]["segment"]["description"] != "Revised description"
    assert effective_annotations(store, job["id"])["tasks"][0]["description"] == "Revised description"
    save_review(store, job["id"], ReviewPatch(segment_id="task-1", expected_revision=1, decision="usable", note="second check"))
    assert effective_annotations(store, job["id"])["tasks"][0]["description"] == "Revised description"
    with pytest.raises(StoreError, match="refresh"):
        save_review(store, job["id"], ReviewPatch(segment_id="task-1", expected_revision=0, decision="excluded"))
    second = process(store)
    assert second["id"] != job["id"]
    assert effective_annotations(store, second["id"])["tasks"][0]["review"]["revision"] == 0
    assert read_result(store, job["id"])["result"]["annotations"]["tasks"][0]["description"] != "Revised description"


def test_review_does_not_fabricate_geometry(captured):
    store, spec = captured
    job = process(store, backend="quality")
    with pytest.raises(StoreError, match="unresolved"):
        create_dataset(store, selection(job))
    save_review(store, job["id"], ReviewPatch(segment_id="task-1", expected_revision=0, decision="usable"))
    dataset = create_dataset(store, selection(job))
    assert read_result(store, job["id"])["result"]["geometry"]["status"] == "missing"
    pytest.importorskip("zarr")
    with pytest.raises(StoreError, match="No consecutive"):
        export_dataset(store, dataset["id"], ExportRequest(format="egowam"))


def test_excluded_child_and_invalid_bounds_are_rejected(captured):
    store, _ = captured
    job = process(store)
    with pytest.raises(StoreError, match="Operation must be contained"):
        save_review(store, job["id"], ReviewPatch(segment_id="task-1", expected_revision=0, decision="usable", end_ns=500_000_000))
    save_review(store, job["id"], ReviewPatch(segment_id="operation-1", expected_revision=0, decision="excluded"))
    with pytest.raises(StoreError, match="individually"):
        create_dataset(store, selection(job))
    with pytest.raises(StoreError, match="excluded"):
        create_dataset(store, selection(job, "operation-1"))


def test_hdf5_preserves_native_sampling_and_frozen_annotations(captured):
    store, _ = captured
    job = process(store)
    dataset = create_dataset(store, selection(job))
    report = export_dataset(store, dataset["id"], ExportRequest())
    with h5py.File(store.root / "exports" / report["id"] / "dataset.h5") as h5:
        group = h5["segments/000000"]
        assert group["left_rgb/timestamp_ns"].shape == (10,)
        assert group["imu/timestamp_ns"].shape == (20,)
        assert group["imu/accel_m_s2"].shape == (20, 3)
        assert len(group["left_rgb/encoded_image"][0]) > 100
        assert json.loads(h5["manifest_json"][()])["sha256"] == dataset["sha256"]
    second = export_dataset(store, dataset["id"], ExportRequest())
    assert second["dataset_sha256"] == report["dataset_sha256"]
    assert second["id"] != report["id"]


def test_source_corruption_blocks_export(captured):
    store, _ = captured
    dataset = create_dataset(store, selection(process(store)))
    packet_path = store.root / store.packet_rows("recording")[0]["path"]
    packet_path.write_bytes(b"damaged")
    with pytest.raises(StoreError):
        export_dataset(store, dataset["id"], ExportRequest())


def test_egowam_zarr_has_nonzero_valid_poses(captured):
    zarr = pytest.importorskip("zarr")
    store, _ = captured
    dataset = create_dataset(store, selection(process(store)))
    report = export_dataset(store, dataset["id"], ExportRequest(format="egowam"))
    group = zarr.open_group(str(store.root / "exports" / report["id"] / report["episodes"][0]["path"]), mode="r")
    assert group["left.obs_ee_pose"].shape == (10, 7)
    assert group["obs_head_pose"][0, 3] == 1
    assert abs(group["left.obs_ee_pose"][0, 0]) > .1
    assert group.attrs["capego"]["origin"] == "synthetic"
    assert group.attrs["total_frames"] == 10


def test_annotation_references_and_time_are_validated():
    with pytest.raises(ValueError, match="Unknown related"):
        AnnotationSet.model_validate({"tasks": [{"id": "t", "start_ns": 0, "end_ns": 10, "description": "task"}],
            "operations": [{"id": "o", "task_id": "t", "start_ns": 1, "end_ns": 9, "description": "op", "hands": ["left"], "object_ids": ["nonexistent"]}]})


def test_vlm_missing_model_fails_per_job_without_fallback(captured, monkeypatch):
    store, _ = captured
    monkeypatch.setenv("CAPEGO_MODEL_ROOT", str(store.root / "no-models"))
    processor = Processor(store)
    try:
        result = processor.submit(BatchRequest(recording_ids=["recording"], backend="local_vlm"))
        job = processor.wait(result["jobs"][0]["id"])
        assert job["status"] == "failed"
        assert job["result"] is None
        assert "Provision" in job["error"]
    finally:
        processor.close()


def test_invalid_hand_frame_splits_training_windows(captured, monkeypatch):
    pytest.importorskip("zarr")
    from capego import processing
    original = processing.synthetic_geometry

    def partial(times):
        geometry = original(times)
        geometry["frames"][4]["hands"]["left"]["wrist_valid"] = False
        return geometry

    monkeypatch.setattr(processing, "synthetic_geometry", partial)
    store, _ = captured
    job = process(store)
    dataset = create_dataset(store, selection(job))
    report = export_dataset(store, dataset["id"], ExportRequest(format="egowam"))
    assert [e["frames"] for e in report["episodes"]] == [4, 5]
    assert report["filtered"][0]["frames"] == 1
    assert report["episodes"][1]["start_ns"] == 500_000_000
    assert read_result(store, job["id"])["result"]["geometry"]["frames"][4]["hands"]["right"]["wrist_valid"] is True
