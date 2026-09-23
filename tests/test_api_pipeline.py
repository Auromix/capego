from fastapi.testclient import TestClient

from capego.api import create_app
from capego.contracts import sequence_digest
from capego.sources import synthetic_packets, synthetic_spec


def test_api_pipeline_review_export_and_access_boundaries(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400
        assert client.get("/").status_code == 200
        assert "Content-Security-Policy" in client.get("/static/app.js").headers
        assert client.post("/api/v1/recordings", content=b"{}", headers={"Content-Length": "invalid"}).status_code == 400
        assert client.post("/api/v1/recordings", content=b"{}", headers={"Content-Length": str(20*1024**2)}).status_code == 413
        spec = synthetic_spec("api-pipeline", width=64, height=48, fps=10, imu_hz=20)
        assert client.post("/api/v1/recordings", json=spec.model_dump()).status_code == 201
        packets = list(synthetic_packets(spec, 1))
        for p in packets:
            assert client.put(f"/api/v1/recordings/{spec.id}/packets/{p.sequence}", json=p.model_dump()).status_code == 200
        assert client.get("/api/v1/processing").json()["total"] == 0
        end = {"packet_count": len(packets), "content_sha256": sequence_digest([(p.sequence, p.digest()) for p in packets]), "ended_at_ns": 1_000_000_000, "reason": "user"}
        assert client.put(f"/api/v1/recordings/{spec.id}/end", json=end).json()["status"] == "complete"
        jid = client.post("/api/v1/processing", json={"recording_ids": [spec.id], "backend": "synthetic"}).json()["jobs"][0]["id"]
        assert app.state.processor.wait(jid)["status"] == "succeeded"
        patch = {"segment_id": "task-1", "expected_revision": 0, "decision": "usable", "description": "reviewed"}
        assert client.post(f"/api/v1/processing/{jid}/reviews", json=patch).json()["revision"] == 1
        assert client.post(f"/api/v1/processing/{jid}/reviews", json=patch).status_code == 409
        response = client.post("/api/v1/datasets", json={"name": "API pipeline", "selections": [{"processing_id": jid, "segment_ids": ["task-1"]}]})
        assert response.status_code == 201
        did = response.json()["id"]
        report = client.post(f"/api/v1/datasets/{did}/exports", json={"format": "hdf5"}).json()
        download = client.get(f"/api/v1/exports/{report['id']}/files/dataset.h5")
        assert download.status_code == 200 and download.content.startswith(b"\x89HDF")
        assert client.get(f"/api/v1/exports/{report['id']}/files/index.sqlite3").status_code == 404
        (tmp_path / "exports" / report["id"] / "dataset.h5").write_bytes(b"broken")
        assert client.get(f"/api/v1/exports/{report['id']}/files/dataset.h5").status_code == 409
