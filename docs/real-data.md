# Real ego data, end to end

The optional EgoDex adapter exercises actual video and provided camera/hand estimates without a physical capture rig. It uses the normal HTTP outbox/receiver path; it is not a direct write into the PC database.

## Download bounded samples

```bash
pip install -e '.[dev,data,export]'
python scripts/fetch_egodex_samples.py --output runtime/real-data
```

The script reads the central directory of Apple's official test ZIP through HTTP Range and downloads three MP4/HDF5 pairs. It rejects full-archive responses and oversized members, verifies ZIP CRCs and writes SHA-256 provenance to `source-manifest.json`. About 21 MB of source files are downloaded. The source ZIP may change upstream: compare file hashes with the published validation manifest when reproducing a specific run.

Source: [EgoDex](https://github.com/apple-aiml-research/ml-egodex). Its dataset is under separate CC-BY-NC-ND terms; CapEgo does not redistribute videos, frame derivatives or converted datasets. These **test-split** clips are only integration fixtures. Training smoke updates are discarded, with no benchmark evaluation or retained checkpoint.

## Run the complete validation

```bash
python scripts/validate_real_pipeline.py --root runtime/real-validation
```

Use a fresh `--root` for each run. It:

1. Replays full 1920×1080 / 30 Hz recordings through a real loopback HTTP receiver and verifies data arrived before capture ended.
2. Kills and restarts the receiver during the longer clip; checks transport failure, backlog, successful drain and raw integrity.
3. Stops the receiver and explicitly runs post-processing on already saved data.
4. Verifies the review gate, then adds clearly labelled **scripted integration-only reviews**. These exercise the workflow and are not human quality acceptance.
5. Freezes a multi-recording snapshot, exports HDF5 and EgoWAM, and compares every native RGB/tracking payload and timestamp in the positive samples.
6. Rejects EgoWAM export of the sample with missing hand confidence rather than filling it with plausible poses.

Outputs stay under the runtime directory. `report.json` includes source/recording hashes, observed transfer state, export paths and limits. This is same-host HTTP validation, not a measured wireless-LAN or physical sensor test.

## Use one pair interactively

```bash
capego serve --root runtime/pc
# Another terminal:
capego import-egodex runtime/real-data/test/add_remove_lid/0.mp4 \
  --outbox runtime/device/egodex-lid.sqlite3
```

The paired `.hdf5` must be beside the video. Capture is paced by video PTS by default; `--fast` removes pacing for a stress test. The command emits its recording ID. Choose `dataset_annotations` in the workbench to use source-provided estimates, or `local_vlm` to independently generate semantic proposals from RGB. Both require review; the VLM path does not compute metric geometry.

## Time, coordinates and missing data

- Decode original MP4 presentation timestamps; preserve them in `source_timestamp_ns` and subtract the first for recording time. HDF5 annotations are paired by frame index per EgoDex's documentation. Reject mismatched counts or non-30-Hz timing. No hardware-synchronization claim is made.
- Preserve full video resolution. Transport re-encodes decoded frames as JPEG quality 95; this is not byte-identical archival of the source MP4. Keep the source pair and hashes locally. HDF5 export is byte-identical to the archived CapEgo packet payloads.
- Set `local_from_world = inverse(first_world_from_camera)`. Local poses are `local_from_world @ world_from_body`; camera-relative poses use `inverse(world_from_camera_at_t) @ world_from_body`. This follows the released EgoDex visualization's direct camera projection convention; no guessed axis flip is applied. Preserve source-native body orientation axes. Local reference axes are the first camera's right/down/forward axes.
- Represent poses in metres and `xyz + wxyz`, with `local_from_body` direction. Map wrists and 20 finger joints explicitly; non-thumb metacarpals are omitted from the 21-point representation. The mapping and initial transform are stored in calibration provenance.
- Source ARKit confidence must meet the configurable threshold (default 0.5). Missing/nonfinite confidence or invalid transforms produce null observations with false masks. Do not synthesize zero vectors, identity poses or confidence=1 for missing hands. Camera poses require finite proper rigid transforms; this numeric validity does not certify tracking accuracy.
- This dataset input contains one RGB stream and source-estimated geometry. No second camera, IMU, object tracks, robot action labels or newly inferred dense hand geometry are invented.

EgoDex's own documentation notes possible annotation errors and RGB/pose projection mismatch. This adapter checks structure and provenance; it does not independently establish geometric accuracy.

## Validate actual training use

```bash
pip install -e '.[training]' -r requirements-upstream-smoke.txt
git clone https://github.com/GaTech-RL2/EgoWAM.git runtime/EgoWAM
git -C runtime/EgoWAM checkout c87617fe37a6ed6a951e6b176ad552200c425c93
python scripts/validate_egowam.py --upstream runtime/EgoWAM \
  --demo-report runtime/real-validation/report.json \
  --output runtime/real-validation/egowam-training.json
```

The script rejects an altered upstream checkout or corrupted export. It runs the original Human transforms and HPTModel, and checks finite/nonzero gradients plus updates in the trunk, action head and world head. The reduced configuration has 60,780 parameters and pooled 8×8 RGB features; it uses no released checkpoints, robot samples or large visual encoder. Passing establishes **actual data use**, not paper reproduction or useful model quality.

Published [execution evidence](../design/validation/2026-09-24-real-data.md) separates the real source replay, imported annotations, local VLM proposals and upstream training result.
