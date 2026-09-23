"""Immutable, content-verified dataset snapshots. Reviews never fill missing geometry."""

from __future__ import annotations

import json
import uuid

from .contracts import DatasetRequest, canonical, sha256
from .processing import effective_annotations, read_result, result_digest
from .storage import StoreError, atomic_write, safe_id, utc_now


def create_dataset(store, request: DatasetRequest):
    items, seen = [], set()
    for selection in request.selections:
        job = read_result(store, selection.processing_id)
        if job["status"] != "succeeded":
            raise StoreError("not_ready", "All selected processing jobs must succeed")
        result = job["result"]
        rec = store.require_complete(job["recording_id"])
        annotations = effective_annotations(store, job["id"])
        spans = {s["id"]: s for s in [*annotations["tasks"], *annotations["operations"]]}
        tasks = {s["id"]: s for s in annotations["tasks"]}
        for segment_id in selection.segment_ids:
            key = (job["id"], segment_id)
            if key in seen:
                raise StoreError("duplicate_selection", "Dataset contains a duplicate source segment", 422)
            seen.add(key)
            if segment_id not in spans:
                raise StoreError("not_found", "Selected segment does not exist", 404)
            span = spans[segment_id]
            decision = span["review"]["decision"]
            blocked = span["needs_review"] or result["quality"]["status"] != "pass"
            if decision == "excluded" or (blocked and decision != "usable"):
                raise StoreError("review_required", "Selected segment is excluded or has unresolved review requirements")
            if "task_id" in span and tasks[span["task_id"]]["review"]["decision"] == "excluded":
                raise StoreError("excluded_parent", "Operation belongs to an excluded task")
            # Selecting a task must not silently reintroduce an excluded/problem operation.
            if "task_id" not in span:
                children = [s for s in annotations["operations"] if s["task_id"] == span["id"]]
                if any(s["review"]["decision"] == "excluded" or (s["needs_review"] and s["review"]["decision"] != "usable") for s in children):
                    raise StoreError("unresolved_child", "Select usable operations individually while this task has excluded/unresolved operations")
            for previous in items:
                if previous["recording_id"] == rec["id"] and max(previous["segment"]["start_ns"], span["start_ns"]) < min(previous["segment"]["end_ns"], span["end_ns"]):
                    raise StoreError("overlapping_selection", "Overlapping source intervals must be exported as separate dataset versions", 422)
            items.append({"recording_id": rec["id"], "source_sha256": rec["end"]["content_sha256"],
                          "processing_id": job["id"], "processing_sha256": result_digest(result),
                          "origin": result["origin"], "segment": span, "annotations": annotations})
    body = {"schema_version": 1, "id": f"dataset-{uuid.uuid4().hex}", "name": request.name,
            "created_at": utc_now(), "items": items}
    encoded = canonical(body)
    digest = sha256(encoded)
    atomic_write(store.root / "datasets" / body["id"] / "manifest.json", encoded)
    with store.connection(write=True) as db:
        db.execute("INSERT INTO datasets VALUES (?,?,?,?,?)", (body["id"], body["name"], encoded.decode(), digest, body["created_at"]))
    return {**body, "sha256": digest}


def get_dataset(store, dataset_id):
    safe_id(dataset_id)
    with store.connection() as db:
        row = db.execute("SELECT body,sha256 FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if not row:
        raise StoreError("not_found", "Dataset not found", 404)
    encoded = row["body"].encode()
    path = store.root / "datasets" / dataset_id / "manifest.json"
    if sha256(encoded) != row["sha256"] or not path.is_file() or path.read_bytes() != encoded:
        raise StoreError("snapshot_corrupt", "Dataset snapshot integrity failed")
    return {**json.loads(encoded), "sha256": row["sha256"]}


def list_datasets(store, limit=100, offset=0):
    with store.connection() as db:
        rows = db.execute("SELECT id,name,sha256,created_at FROM datasets ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    return {"items": [dict(r) for r in rows], "total": total}


def validate_sources(store, dataset):
    for item in dataset["items"]:
        rec = store.require_complete(item["recording_id"])
        result = read_result(store, item["processing_id"])["result"]
        if rec["end"]["content_sha256"] != item["source_sha256"] or result_digest(result) != item["processing_sha256"]:
            raise StoreError("source_changed", "Dataset source no longer matches its snapshot")
