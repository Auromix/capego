# Running CapEgo

[English README](../README.md) · [中文说明](../README.zh-CN.md)

## Install and inspect

Use Python 3.11+ and a virtual environment. From the repository root:

```bash
pip install -e '.[dev,export]'
capego doctor
capego --help
```

Optional extras: `data` for EgoDex decoding, `export` for EgoWAM Zarr, `vlm` for the local Qwen adapter, `training` plus `requirements-upstream-smoke.txt` for upstream validation. The base receiver does not import Torch or require a GPU.

## Receive and capture

```bash
capego serve --root runtime/pc
# Second terminal:
capego simulate --seconds 10 --fps 30
```

Open http://localhost:8765. A recording becomes selectable for processing after it ends and passes integrity verification. `simulate` generates synthetic images/IMU and clearly marks that origin. [Real-data replay](real-data.md) exercises the same transport with actual video.

```bash
capego verify RECORDING_ID --root runtime/pc
capego resume runtime/device/RECORDING_ID.sqlite3
```

`resume` drains an existing outbox; it never resumes physical capture or creates another recording. Cache exhaustion is an abnormal end. Stopping capture does not discard pending transfers. IDs and outbox paths are printed by the capture commands.

## LAN configuration

Set the same `CAPEGO_TOKEN` in the receiver and sender shells through your normal secret management. Then:

```bash
# PC receiver; substitute its actual LAN address:
capego serve --root runtime/pc --host 0.0.0.0 --allowed-host PC_LAN_IP
# Capture machine:
capego simulate --url http://PC_LAN_IP:8765 --seconds 10
```

Enter that token in the workbench connection field. Use a trusted LAN or TLS reverse proxy: direct HTTP is unencrypted. Keep tokens out of shell history, source files and reports. Runtime directories are Git-ignored by default.

## Explicit processing and review

In the workbench, select complete recordings and choose a backend:

| Backend | Input and result |
| --- | --- |
| `quality` | Timing gaps and exposure/contrast; creates a task requiring review, without inferred geometry |
| `synthetic` | Synthetic origin only; deterministic test annotations/geometry |
| `dataset_annotations` | EgoDex source annotations and tracking already archived; review required |
| `local_vlm` | A separately provisioned local Qwen2.5-VL model proposes task/operation semantics; review required; no geometry or object tracks |

Processing can also run with the receiver stopped:

```bash
capego process RECORDING_ID --root runtime/pc --backend dataset_annotations
```

For the VLM backend, install `.[vlm]` and provision Qwen2.5-VL-3B-Instruct under `models/qwen2.5-vl/` (or set `CAPEGO_MODEL_ROOT`). See the [model setup runbook](../design/validation/ubuntu-runbook.md). Runtime loading is local-only, with no remote code. Four sampled frames produce coarse proposals, not dense segmentation. Invalid model output fails the job and is retained with diagnostics; there is no synthetic fallback.

Review task descriptions, time bounds and uncertain operations before accepting them. A review can change annotation text and inclusion, but cannot fill missing geometry. Rerunning processing creates a new immutable result; existing reviews and datasets retain their versions.

## Freeze and export

Select reviewed segments in the workbench, name a dataset and export; or:

```bash
capego dataset 'Tabletop v1' PROCESSING_ID:task-1 --root runtime/pc
capego export DATASET_ID --root runtime/pc --format hdf5
capego export DATASET_ID --root runtime/pc --format egowam --fps 10
```

HDF5 preserves native timestamps and packet payloads. EgoWAM aligns only within the configured tolerance, excludes missing/invalid wrists or camera poses, and splits windows at gaps. The export report records sources and content hashes. Exporting alone is not a training test; run the [upstream validation](real-data.md#validate-actual-training-use).

## Current operational limits

Single-user workbench; per-packet JSON/base64 transport; no production hardware encoder or device driver. Raw chunking is storage organization, not semantic segmentation. The VLM backend does not recover metric hand poses. GPU support, physical synchronization and sustained production throughput need separate measurements.
