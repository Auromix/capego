"""Verified immutable dataset exports with target-specific writers."""

import json
import uuid

from .contracts import ExportRequest, canonical, sha256
from .datasets import get_dataset, validate_sources
from .exporters.egowam import EGOWAM_COMMIT as EGOWAM_COMMIT
from .exporters.egowam import write_egowam
from .exporters.native import write_hdf5
from .storage import StoreError, atomic_write, fsync_dir, safe_id


def export_dataset(store, dataset_id, config: ExportRequest):
    dataset = get_dataset(store, dataset_id)
    validate_sources(store, dataset)
    export_id = f"export-{uuid.uuid4().hex}"
    output = store.root / "exports" / export_id
    output.mkdir(parents=True, exist_ok=False)
    try:
        report = (
            write_hdf5(store, dataset, output)
            if config.format == "hdf5"
            else write_egowam(store, dataset, output, config)
        )
        report.update(
            {
                "id": export_id,
                "dataset_id": dataset_id,
                "dataset_sha256": dataset["sha256"],
                "config": config.model_dump(),
                "origins": sorted({i["origin"] for i in dataset["items"]}),
            }
        )
        report["content_files"] = {
            str(p.relative_to(output)): sha256(p.read_bytes())
            for p in sorted(output.rglob("*"))
            if p.is_file()
        }
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
