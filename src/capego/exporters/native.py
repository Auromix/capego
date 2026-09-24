"""Preserve native stream samples in HDF5."""

import json
import os

import h5py
import numpy as np

from ..contracts import canonical
from ..processing import read_result


def write_hdf5(store, dataset, output):
    with h5py.File(output / "dataset.h5", "w") as file:
        file.attrs["schema"] = "capego.native.v1"
        file.create_dataset(
            "manifest_json", data=canonical(dataset).decode(), dtype=h5py.string_dtype()
        )
        for i, item in enumerate(dataset["items"]):
            group = file.create_group(f"segments/{i:06d}")
            rec = store.recording(item["recording_id"])
            result = read_result(store, item["processing_id"])["result"]
            begin, end = item["segment"]["start_ns"], item["segment"]["end_ns"]
            geometry = {
                **result["geometry"],
                "frames": [
                    f for f in result["geometry"]["frames"] if begin <= f["timestamp_ns"] < end
                ],
            }
            for key, value in {
                "calibration": rec["spec"]["calibration"],
                "clock": rec["spec"]["clock"],
                "annotations": item["annotations"],
                "quality": result["quality"],
                "geometry": geometry,
            }.items():
                group.create_dataset(
                    f"{key}_json", data=canonical(value).decode(), dtype=h5py.string_dtype()
                )
            begin, end = item["segment"]["start_ns"], item["segment"]["end_ns"]
            for stream in rec["spec"]["streams"]:
                rows = [
                    r
                    for r in store.packet_rows(rec["id"])
                    if r["stream_id"] == stream["id"] and begin <= r["timestamp_ns"] < end
                ]
                packets = [store.read_packet(r) for r in rows]
                sg = group.create_group(stream["id"])
                sg.attrs["stream_json"] = canonical(stream).decode()
                for key in ("timestamp_ns", "source_timestamp_ns", "sequence"):
                    sg.create_dataset(
                        key, data=np.array([getattr(p, key) for p in packets], dtype=np.int64)
                    )
                sg.create_dataset(
                    "clock_id",
                    data=np.array([p.clock_id for p in packets], dtype=h5py.string_dtype()),
                )
                if stream["kind"] == "rgb":
                    payloads = sg.create_dataset(
                        "encoded_image",
                        shape=(len(packets),),
                        dtype=h5py.vlen_dtype(np.dtype("uint8")),
                    )
                    for j, packet in enumerate(packets):
                        payloads[j] = np.frombuffer(packet.payload(), dtype=np.uint8)
                    sg.create_dataset(
                        "codec",
                        data=np.array([p.codec for p in packets], dtype=h5py.string_dtype()),
                    )
                elif stream["kind"] == "tracking":
                    sg.create_dataset(
                        "tracking_json",
                        data=np.array(
                            [p.payload().decode() for p in packets], dtype=h5py.string_dtype()
                        ),
                    )
                else:
                    values = [json.loads(p.payload()) for p in packets]
                    for key in ("accel_m_s2", "gyro_rad_s"):
                        sg.create_dataset(
                            key,
                            data=np.array([v[key] for v in values], dtype=np.float64).reshape(
                                -1, 3
                            ),
                        )
        file.flush()
    with open(output / "dataset.h5", "rb") as file:
        os.fsync(file.fileno())
    return {
        "files": ["dataset.h5"],
        "segments": len(dataset["items"]),
        "format": "capego.native.v1",
    }
