# Changelog

## Unreleased

- Adopt Apache-2.0 and add English-default / Simplified Chinese READMEs, contribution guidance and third-party notices.
- Separate quality/fixture/provided-annotation backends and HDF5/EgoWAM export writers.
- Add real EgoDex MP4/HDF5 replay through the continuous HTTP capture path, with source hashes, native PTS, explicit geometry validity and 21-joint mapping.
- Add typed tracking packets and an explicit `dataset_annotations` processing backend. Missing confidence stays invalid.
- Add bounded public-data download and real pipeline checks: receiver crash/restart, independent processing, review gates and native export roundtrip.
- Validate real ego samples using the pinned EgoWAM Human loader and reduced world/action training configuration.
- Retain the existing synthetic fault tests, local VLM backend, offline workbench, immutable snapshots and demonstration video.

This is an unreleased prototype; no physical-device or production-performance claim is made.
