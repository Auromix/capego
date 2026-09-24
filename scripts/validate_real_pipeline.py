"""Exercise real EgoDex pairs through HTTP, receiver restart, review and export.

Creates an isolated integration-only dataset. The scripted 'usable' reviews test
workflow transitions and are explicitly NOT human semantic/geometry acceptance.
No downloaded data, derived frames or trained checkpoints should be published.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import h5py
import httpx
import numpy as np

from capego.capture import CaptureSession, HTTPTransport, Outbox
from capego.contracts import BatchRequest, canonical, sha256
from capego.importers.egodex import EgoDexSource
from capego.processing import Processor, list_jobs
from capego.storage import Store


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("runtime/real-data"))
    parser.add_argument("--root", type=Path, default=Path("runtime/real-validation"))
    args = parser.parse_args()
    args.root = args.root.resolve()
    if (args.root / "pc" / "index.sqlite3").exists():
        raise ValueError("Use a fresh --root for an isolated validation run")
    args.root.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.pop("CAPEGO_TOKEN", None)
    server = None
    client = httpx.Client(base_url=url, timeout=120, trust_env=False)
    log = open(args.root / "receiver.log", "w")

    def start_server():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "capego.cli",
                "serve",
                "--root",
                str(args.root / "pc"),
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=log,
            env=env,
        )
        try:
            for _ in range(200):
                try:
                    if client.get("/health").status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            raise RuntimeError("Receiver failed to start; see receiver.log")
        except BaseException:
            process.kill()
            process.wait()
            raise

    def request(method, path, body=None):
        response = client.request(method, path, json=body)
        response.raise_for_status()
        return response.json()

    report = {
        "status": "running",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "scope": "real public test-split clips; isolated software integration; no benchmark claims",
        "transport": "real HTTP loopback; physical LAN and sensor synchronization not measured",
        "records": [],
        "review": "scripted integration-only review, not human acceptance",
    }
    try:
        server = start_server()
        store = Store(args.root / "pc")
        jobs = []
        for task in ("add_remove_lid", "screw_unscrew_bottle_cap", "basic_fold"):
            source = EgoDexSource(args.data / "test" / task / "0.mp4", recording_id="real-" + task)
            rid = source.spec.id
            transport = HTTPTransport(url)
            outbox = Outbox(args.root / "device" / f"{rid}.sqlite3")
            session = CaptureSession(source.spec, transport, outbox)
            maximum_pending, maximum_cache, streamed_before_end, observed_outage = (
                0,
                0,
                False,
                False,
            )
            restarted, stopped_at = False, None
            started = time.monotonic()
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(session.record, source.packets(), True, source.duration_ns)
                    while not future.done() or (stopped_at is not None and not restarted):
                        stats = outbox.stats()
                        maximum_pending = max(maximum_pending, stats["pending"])
                        maximum_cache = max(maximum_cache, stats["cache_bytes"])
                        try:
                            rec = store.recording(rid)
                            streamed_before_end |= rec["count"] > 0 and rec["end"] is None
                        except Exception:
                            pass  # receiver may not have created the recording yet
                        if (
                            task == "basic_fold"
                            and stopped_at is None
                            and time.monotonic() - started > 2
                        ):
                            server.kill()  # actual receiver process failure, not a mocked send
                            server.wait()
                            stopped_at = time.monotonic()
                        if stopped_at and not restarted:
                            observed_outage |= session.last_transport_error is not None
                            if time.monotonic() - stopped_at > 2:
                                server = start_server()
                                restarted = True
                        time.sleep(0.05)
                    end = future.result()
                require(end.reason == "source_exhausted", f"Unexpected capture stop: {end.reason}")
                require(session.wait_saved(120), f"Capture did not drain: {session.error}")
                require(streamed_before_end, "No evidence of durable PC data before capture ended")
                verification = request("POST", f"/api/v1/recordings/{rid}/verification")
                require(verification["status"] == "complete", "Raw integrity verification failed")
                require(outbox.stats()["pending"] == 0, "Unacknowledged packets remain")
                require(
                    not list_jobs(store)["items"]
                    or rid not in [j["recording_id"] for j in list_jobs(store)["items"]],
                    "Data arrival unexpectedly started processing",
                )
                if restarted:
                    require(
                        observed_outage and maximum_pending > 0,
                        "No observed retry/backlog during receiver failure",
                    )
            finally:
                session.close()
                transport.close()
            # Stop receiver and run processing independently in this process.
            server.terminate()
            server.wait(15)
            processor = Processor(store)
            try:
                batch = processor.submit(
                    BatchRequest(recording_ids=[rid], backend="dataset_annotations")
                )
                job = processor.wait(batch["jobs"][0]["id"], 120)
                require(job["status"] == "succeeded", f"Processing failed: {job['error']}")
            finally:
                processor.close()
            server = start_server()
            selection = {"processing_id": job["id"], "segment_ids": ["task-1"]}
            rejected = client.post(
                "/api/v1/datasets", json={"name": "must require review", "selections": [selection]}
            )
            require(
                rejected.status_code == 409
                and rejected.json()["error"]["code"] == "review_required",
                "Review gate was bypassed",
            )
            request(
                "POST",
                f"/api/v1/processing/{job['id']}/reviews",
                {
                    "segment_id": "task-1",
                    "expected_revision": 0,
                    "decision": "usable",
                    "note": "Scripted isolated integration test only; not human semantic/geometry acceptance",
                },
            )
            frames = job["result"]["geometry"]["frames"]
            wrists = {
                s: sum(f["hands"][s]["wrist_valid"] for f in frames) for s in ("left", "right")
            }
            record = {
                "recording_id": rid,
                "sample": f"test/{task}/0",
                "frames": len(source.times),
                "resolution": [source.spec.streams[0].width, source.spec.streams[0].height],
                "fps": 30,
                "duration_ns": source.duration_ns,
                "packets": outbox.stats()["produced"],
                "chunks": len(list((store.root / "recordings" / rid / "chunks").iterdir())),
                "source_files": source.spec.calibration["dataset"]["files_sha256"],
                "source_sha256": store.recording(rid)["end"]["content_sha256"],
                "pending_at_end": outbox.stats()["pending"],
                "peak_pending": maximum_pending,
                "peak_cache_bytes": maximum_cache,
                "streamed_before_end": streamed_before_end,
                "receiver_crash_recovered": restarted,
                "transport_error_observed": observed_outage,
                "processing_with_receiver_stopped": True,
                "processing_id": job["id"],
                "quality": job["result"]["quality"]["status"],
                "valid_wrists": wrists,
                "wall_seconds": round(time.monotonic() - started, 3),
            }
            if task == "basic_fold":
                require(
                    wrists == {"left": 0, "right": 0},
                    "Missing confidence must not become valid supervision",
                )
                dataset = request(
                    "POST",
                    "/api/v1/datasets",
                    {"name": "Negative test: missing confidence", "selections": [selection]},
                )
                failure = client.post(
                    f"/api/v1/datasets/{dataset['id']}/exports", json={"format": "egowam"}
                )
                require(
                    failure.status_code == 422
                    and failure.json()["error"]["code"] == "no_training_samples",
                    "Missing geometry was exported as valid",
                )
                record["training_export_rejected"] = "no_training_samples"
            else:
                jobs.append(selection)
            report["records"].append(record)
            print(json.dumps(record), flush=True)
        dataset = request(
            "POST", "/api/v1/datasets", {"name": "EgoDex integration only", "selections": jobs}
        )
        reports, exports = {}, {}
        for fmt in ("hdf5", "egowam"):
            reports[fmt] = request(
                "POST", f"/api/v1/datasets/{dataset['id']}/exports", {"format": fmt}
            )
            exports[fmt] = str(store.root / "exports" / reports[fmt]["id"])
        # Byte-for-byte archived image/tracking payload roundtrip and exact native timestamps.
        roundtrip = 0
        with h5py.File(Path(exports["hdf5"]) / "dataset.h5", "r") as h5:
            for index, item in enumerate(dataset["items"]):
                group = h5[f"segments/{index:06d}"]
                for stream, key in (("rgb", "encoded_image"), ("tracking", "tracking_json")):
                    packets = [
                        store.read_packet(row)
                        for row in store.packet_rows(item["recording_id"])
                        if row["stream_id"] == stream
                    ]
                    require(
                        np.array_equal(
                            group[stream + "/timestamp_ns"][:], [p.timestamp_ns for p in packets]
                        ),
                        "Native timestamps changed",
                    )
                    for n, packet in enumerate(packets):
                        saved = group[stream + "/" + key][n]
                        require(
                            bytes(saved) == packet.payload(),
                            "Native payload changed in HDF5 export",
                        )
                        roundtrip += 1
        report.update(
            {
                "status": "passed",
                "dataset_id": dataset["id"],
                "dataset_sha256": dataset["sha256"],
                "exports": exports,
                "egowam_episodes": reports["egowam"]["episodes"],
                "egowam_filtered": reports["egowam"]["filtered"],
                "native_payloads_verified": roundtrip,
                "source_manifest_sha256": sha256((args.data / "source-manifest.json").read_bytes()),
                "missing_streams": ["stereo", "imu"],
                "receiver_stopped_after_validation": True,
            }
        )
        (args.root / "report.json").write_bytes(canonical(report))
        print(
            json.dumps(
                {"status": "passed", "report": str(args.root / "report.json"), "exports": exports},
                indent=2,
            )
        )
    finally:
        if server and server.poll() is None:
            server.terminate()
            server.wait(15)
        client.close()
        log.close()


if __name__ == "__main__":
    main()
