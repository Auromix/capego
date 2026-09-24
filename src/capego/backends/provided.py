"""Promote archived source estimates into a reviewable processing version."""

from ..annotations import AnnotationSet
from ..geometry import TrackingFrame


def provided_annotations(store, rec, rows):
    metadata = rec["spec"]["calibration"].get("dataset", {})
    if (
        rec["spec"]["origin"] not in {"dataset", "replay"}
        or metadata.get("provider") != "egodex-arkit-provided-v1"
    ):
        raise ValueError("dataset_annotations requires an EgoDex recording with source provenance")
    streams = {s["id"] for s in rec["spec"]["streams"] if s["kind"] == "tracking"}
    frames = [
        TrackingFrame.model_validate_json(store.read_packet(row).payload()).model_dump()
        for row in rows
        if row["stream_id"] in streams
    ]
    if len(streams) != 1 or not frames:
        raise ValueError("Exactly one nonempty provided tracking stream is required")
    annotations = AnnotationSet.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "start_ns": 0,
                    "end_ns": rec["end"]["ended_at_ns"],
                    "description": metadata.get("description")
                    or "Source episode; description unavailable",
                    "needs_review": True,
                }
            ],
            "operations": [],
            "objects": [],
        }
    )
    geometry = {**metadata["geometry"], "frames": frames}
    provenance = {
        "backend": "dataset_annotations",
        "source": metadata,
        "semantics": "provided episode-level annotation; no task boundary inference",
        "geometry": "provided ARKit estimates; not a locally run estimation model",
    }
    return annotations, geometry, provenance
