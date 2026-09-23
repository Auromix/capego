"""Small, scriptable entry points. Tokens are read from the environment only."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from .capture import CaptureSession, HTTPTransport, Outbox
from .sources import synthetic_packets, synthetic_spec
from .storage import Store


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(prog="capego")
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the receiver and offline workbench")
    serve.add_argument("--root", default="runtime/pc")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allowed-host", action="append", default=[])
    sim = sub.add_parser("simulate", help="Continuously send synthetic RGB + IMU")
    sim.add_argument("--url", default="http://127.0.0.1:8765")
    sim.add_argument("--seconds", type=float, default=5)
    sim.add_argument("--fps", type=float, default=10)
    sim.add_argument("--imu-hz", type=float, default=100)
    sim.add_argument("--width", type=int, default=320)
    sim.add_argument("--height", type=int, default=240)
    sim.add_argument("--chunk-seconds", type=float, default=1)
    sim.add_argument("--id", default=None)
    sim.add_argument("--outbox", default=None)
    sim.add_argument("--cache-mib", type=float, default=256)
    sim.add_argument("--wait", type=float, default=30)
    sim.add_argument("--fast", action="store_true", help="Disable wall-clock pacing (stress test)")
    resume = sub.add_parser("resume", help="Drain an existing outbox, never restart capture")
    resume.add_argument("outbox")
    resume.add_argument("--url", default="http://127.0.0.1:8765")
    resume.add_argument("--wait", type=float, default=60)
    verify = sub.add_parser("verify")
    verify.add_argument("recording_id")
    verify.add_argument("--root", default="runtime/pc")
    process = sub.add_parser("process", help="Explicitly process completed recordings (receiver may be stopped)")
    process.add_argument("recording_ids", nargs="+")
    process.add_argument("--root", default="runtime/pc")
    process.add_argument("--backend", choices=["quality", "synthetic", "local_vlm"], default="quality")
    process.add_argument("--model-path", default=None)
    process.add_argument("--hint", default="")
    process.add_argument("--wait", type=float, default=3600)
    dataset = sub.add_parser("dataset", help="Freeze named dataset with proc-id:segment-id selections")
    dataset.add_argument("name")
    dataset.add_argument("selections", nargs="+")
    dataset.add_argument("--root", default="runtime/pc")
    export = sub.add_parser("export")
    export.add_argument("dataset_id")
    export.add_argument("--root", default="runtime/pc")
    export.add_argument("--format", choices=["hdf5", "egowam"], default="hdf5")
    export.add_argument("--fps", type=float, default=10)
    sub.add_parser("doctor", help="Report local environment without printing credentials")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            import platform
            import shutil
            result = {"python": platform.python_version(), "platform": platform.platform(),
                      "receiver_default": "127.0.0.1:8765", "disk_free_bytes": shutil.disk_usage(Path.cwd()).free,
                      "token_configured": bool(os.environ.get("CAPEGO_TOKEN"))}
            try:
                import torch
                result["torch"] = torch.__version__
                result["cuda_available"] = torch.cuda.is_available()
                result["mps_available"] = torch.backends.mps.is_available()
                if torch.cuda.is_available():
                    result["gpu"] = torch.cuda.get_device_name(0)
                    result["vram_bytes"] = torch.cuda.get_device_properties(0).total_memory
            except ImportError:
                result["torch"] = "not installed"
            emit(result)
        elif args.command == "process":
            from .contracts import BatchRequest
            from .processing import Processor
            processor = Processor(Store(args.root))
            try:
                batch = processor.submit(BatchRequest(recording_ids=args.recording_ids, backend=args.backend, hint=args.hint, model_path=args.model_path))
                jobs = [processor.wait(j["id"], args.wait) if j.get("id") else j for j in batch["jobs"]]
                emit({"batch_id": batch["batch_id"], "jobs": [{k: j.get(k) for k in ("id", "recording_id", "status", "error")} for j in jobs]})
                return 0 if all(j["status"] == "succeeded" for j in jobs) else 1
            finally:
                processor.close()
        elif args.command == "dataset":
            from .contracts import DatasetRequest
            from .datasets import create_dataset
            selections = {}
            for text in args.selections:
                pid, sid = text.split(":", 1)
                selections.setdefault(pid, []).append(sid)
            emit(create_dataset(Store(args.root), DatasetRequest(name=args.name, selections=[{"processing_id": pid, "segment_ids": sids} for pid, sids in selections.items()])))
        elif args.command == "export":
            from .contracts import ExportRequest
            from .exporting import export_dataset
            emit(export_dataset(Store(args.root), args.dataset_id, ExportRequest(format=args.format, fps=args.fps)))
        elif args.command == "serve":
            import uvicorn

            from .api import create_app
            token = os.environ.get("CAPEGO_TOKEN")
            if args.host not in {"127.0.0.1", "localhost", "::1"} and not token:
                raise ValueError("LAN binding requires CAPEGO_TOKEN and explicit --allowed-host PC_IP")
            hosts = ["localhost", "127.0.0.1", "[::1]", *args.allowed_host]
            if args.host not in {"0.0.0.0", "::"}:
                hosts.append(args.host)
            uvicorn.run(create_app(args.root, token=token, allowed_hosts=hosts), host=args.host, port=args.port)
        elif args.command == "verify":
            result = Store(args.root).verify(args.recording_id)
            emit(result)
            return 0 if result["status"] == "complete" else 1
        elif args.command in {"simulate", "resume"}:
            transport = HTTPTransport(args.url, os.environ.get("CAPEGO_TOKEN"))
            session = None
            try:
                if args.command == "resume":
                    outbox = Outbox(args.outbox)
                    session = CaptureSession.resume(transport, outbox)
                else:
                    if not 0 < args.seconds <= 86400:
                        raise ValueError("seconds must be in (0, 86400]")
                    rid = args.id or f"sim-{uuid.uuid4().hex[:16]}"
                    spec = synthetic_spec(rid, width=args.width, height=args.height, fps=args.fps,
                                          imu_hz=args.imu_hz, chunk_seconds=args.chunk_seconds)
                    outbox = Outbox(args.outbox or Path("runtime/device") / f"{rid}.sqlite3", int(args.cache_mib * 1024**2))
                    session = CaptureSession(spec, transport, outbox)
                    session.record(synthetic_packets(spec, args.seconds), realtime=not args.fast, duration_ns=int(args.seconds * 1e9))
                saved = session.wait_saved(args.wait)
                result = {"recording_id": session.spec.id, "saved": saved, "outbox": str(outbox.path),
                          **outbox.stats(), "error": session.error, "transport_error": session.last_transport_error}
                if saved:
                    result["verification"] = transport.request("POST", f"/api/v1/recordings/{session.spec.id}/verification")
                    saved = result["verification"]["status"] == "complete"
                emit(result)
                return 0 if saved else 2
            finally:
                if session:
                    session.close()
                transport.close()
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        emit({"error": type(exc).__name__, "message": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
