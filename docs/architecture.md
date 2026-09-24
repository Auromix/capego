# Code architecture

CapEgo is a small Python package with an offline web workbench. Keep domain contracts independent of optional model, decoder and training libraries. The product/system design authority remains [`design/`](../design/README.md).

```text
src/capego/
  contracts.py       Wire requests, packets, acknowledgements and hashes
  geometry.py        Typed metric poses, 21-joint masks and null semantics
  capture.py         Source iteration, concurrent sender, durable outbox
  sources.py         Synthetic fixtures and archived recording replay
  importers/         Public dataset sources (EgoDex)
  storage.py         Raw chunk files, transactional index and integrity checks
  processing.py      Explicit jobs, immutable results and review revisions
  backends/          Quality checks, synthetic fixtures, provided annotations
  vlm.py             Optional local semantic model adapter
  datasets.py        Immutable reviewed-content snapshots
  exporting.py       Verified export lifecycle and target dispatch
  exporters/         Native HDF5, EgoWAM and bounded time alignment
  api.py             HTTP routes and workbench asset serving
  cli.py             Thin commands that invoke the same components
  static/            Offline browser workbench: state, HTTP client, UI helpers, app
```

## Add a source

Produce a `RecordingSpec` and a chronological iterator of `Packet` values. Declare only available streams. Sequence numbers are global and contiguous across streams; `timestamp_ns` is recording-relative and `source_timestamp_ns` preserves source time. Pass the iterator to `CaptureSession.record()` with an explicit duration. Do not bypass the receiver's durable acknowledgement path or overwrite raw data with derived estimates.

`EgoDexSource` performs pair/frame-count/clock preflight, preserves source hashes and emits RGB plus typed tracking. Importing a dataset is recorded as `origin=dataset`, not as a new physical sensor measurement.

## Add a processing backend

Keep algorithms separate from job scheduling, storage and review. `Processor` owns readiness checks, per-recording failure, immutable result writes and version identity. A backend returns validated `AnnotationSet`, geometry and provenance, and must explicitly represent missing outputs. Register its explicit name in `BatchRequest`, the CLI and workbench selector. Optional dependencies load inside the adapter, not at module import time.

Quality checks use native sampling. Semantic models cannot turn a review decision into geometry. Imported estimates retain their provider and confidence policy. Local VLM jobs do not silently borrow imported poses or substitute synthetic outputs.

## Add an export target

Implement a writer under `exporters/`. The export coordinator verifies the snapshot and raw/processing hashes before dispatch, creates a fresh output directory, hashes output files and marks failed exports. Writers do not edit source recordings, processing results, reviews or snapshots.

Document a named target repository/version, coordinate convention, time alignment, required fields and missingness handling. Validate with that target's actual loader and training use before claiming support. `aria_bimanual` in the EgoWAM adapter is a loader compatibility label; provenance identifies the actual ego source and does not claim Aria hardware capture.

## Compatibility

Protocol v1 adds `origin=dataset`, `kind=tracking`, `codec=tracking_json` and `backend=dataset_annotations`. Existing RGB/IMU clients still work; older receivers reject the new enum values, so update both endpoints before dataset replay. Raw data, processing results and dataset snapshots have separate identities and lifecycles.

The native HDF5 schema stores tracking as a JSON stream alongside RGB/IMU when present. The Zarr adapter pins Zarr 3.1.5 because its variable-length bytes extension remains experimental. Package upgrades require upstream-loader regression checks.
