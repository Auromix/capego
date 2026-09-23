"""Reproducible hardware-free HTTP capture -> process -> snapshot -> export demo."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("runtime/demo"))
    parser.add_argument("--egowam", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    # Demo is loopback only and has no need to inherit a real receiver credential.
    env.pop("CAPEGO_TOKEN", None)
    server = subprocess.Popen([sys.executable, "-m", "capego.cli", "serve", "--root", str(args.root / "pc"), "--port", str(port)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    url = f"http://127.0.0.1:{port}"
    client = httpx.Client(base_url=url, timeout=60, trust_env=False)
    try:
        deadline = time.monotonic()+20
        while True:
            try:
                if client.get("/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Demo receiver failed to start")
            time.sleep(.1)
        rid = f"demo-{uuid.uuid4().hex[:12]}"
        capture = subprocess.run([sys.executable, "-m", "capego.cli", "simulate", "--url", url, "--seconds", "2",
            "--id", rid, "--width", "160", "--height", "120", "--imu-hz", "50", "--outbox", str(args.root / "device" / f"{rid}.sqlite3")],
            capture_output=True, text=True, check=True, env=env)
        result = json.loads(capture.stdout)
        assert result["saved"] and result["pending"] == 0
        assert not client.get("/api/v1/processing").json()["items"] or rid not in [j["recording_id"] for j in client.get("/api/v1/processing").json()["items"]]
        response = client.post("/api/v1/processing", json={"recording_ids": [rid], "backend": "synthetic"})
        response.raise_for_status()
        jid = response.json()["jobs"][0]["id"]
        deadline = time.monotonic()+60
        while True:
            job = client.get(f"/api/v1/processing/{jid}").json()
            if job["status"] in {"succeeded", "failed"}:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Processing timed out")
            time.sleep(.1)
        assert job["status"] == "succeeded", job
        response = client.post("/api/v1/datasets", json={"name": "Synthetic pipeline demo", "selections": [{"processing_id": jid, "segment_ids": ["task-1"]}]})
        response.raise_for_status()
        did = response.json()["id"]
        exports = {}
        for fmt in ["hdf5"] + (["egowam"] if args.egowam else []):
            response = client.post(f"/api/v1/datasets/{did}/exports", json={"format": fmt})
            response.raise_for_status()
            exports[fmt] = str(args.root / "pc" / "exports" / response.json()["id"])
        report = {"status": "passed", "origin": "synthetic", "recording_id": rid, "packets": result["produced"],
                  "processing_id": jid, "dataset_id": did, "exports": exports, "receiver_stopped_after_demo": True}
        (args.root / "demo-report.json").write_text(json.dumps(report, indent=2)+"\n")
        print(json.dumps(report, indent=2))
    finally:
        client.close()
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(5)


if __name__ == "__main__":
    main()
