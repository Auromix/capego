import threading
import time

import pytest
from fastapi.testclient import TestClient

from capego.api import create_app
from capego.capture import CaptureSession, Outbox, Unavailable
from capego.contracts import EndRecording, PacketAck, sequence_digest
from capego.sources import synthetic_packets, synthetic_spec
from capego.storage import Store, StoreError


class LocalTransport:
    def __init__(self, store):
        self.store = store
        self.online = True
        self.lose_ack_once = False

    def ready(self):
        if not self.online:
            raise Unavailable("offline")
        return self.store.ready()

    def create(self, spec):
        self.ready()
        return self.store.create(spec)

    def send(self, packet):
        self.ready()
        ack = self.store.receive(packet)
        if self.lose_ack_once:
            self.lose_ack_once = False
            raise Unavailable("ACK lost after durable write")
        return ack

    def end(self, recording_id, end):
        self.ready()
        return self.store.end(recording_id, end)


def setup_capture(tmp_path, **kwargs):
    spec = synthetic_spec(
        "test-recording", width=64, height=48, fps=5, imu_hz=20, chunk_seconds=0.2
    )
    store = Store(tmp_path / "pc", min_free_bytes=0)
    transport = LocalTransport(store)
    outbox = Outbox(tmp_path / "device" / "outbox.sqlite3", **kwargs)
    return (
        spec,
        store,
        transport,
        outbox,
        CaptureSession(spec, transport, outbox, retry_delay=0.005),
    )


def freeze(packets, reason="user", ended_at_ns=1_000_000_000):
    return EndRecording(
        packet_count=len(packets),
        content_sha256=sequence_digest([(p.sequence, p.digest()) for p in packets]),
        ended_at_ns=ended_at_ns,
        reason=reason,
    )


def test_continuous_receive_and_cache_release_before_end(tmp_path):
    spec, store, transport, outbox, session = setup_capture(tmp_path)
    release_source = threading.Event()
    source_held = threading.Event()

    def source():
        for index, packet in enumerate(synthetic_packets(spec, 1)):
            yield packet
            if index == 4:
                source_held.set()
                assert release_source.wait(20), "Test must release the unfinished source"

    producer = threading.Thread(
        target=lambda: session.record(source(), realtime=False, duration_ns=1_000_000_000)
    )
    producer.start()
    deadline = time.monotonic() + 15
    try:
        assert source_held.wait(10)
        while time.monotonic() < deadline:
            if outbox.stats()["produced"] >= 5 and outbox.stats()["pending"] == 0:
                break
            time.sleep(0.01)
        rec = store.recording(spec.id)
        assert rec["status"] == "recording"
        assert rec["count"] >= 5
        assert outbox.stats()["cache_bytes"] == 0
        assert producer.is_alive(), "Data must arrive while acquisition is still running"
        release_source.set()
        producer.join(15)
        assert session.wait_saved(15)
        assert store.require_complete(spec.id)["count"] == 30
        assert len(list((store.root / "recordings" / spec.id / "chunks").iterdir())) == 5
    finally:
        release_source.set()
        session.close()
        producer.join(15)


def test_disconnect_lost_ack_and_resume_do_not_duplicate(tmp_path):
    spec, store, transport, outbox, session = setup_capture(tmp_path)
    session.start()
    transport.online = False
    session.record(synthetic_packets(spec, 0.5), realtime=False, duration_ns=500_000_000)
    assert outbox.stats()["pending"] == 16
    assert not session.wait_saved(0.03)
    session.close()
    transport.online = True
    transport.lose_ack_once = True
    resumed = CaptureSession.resume(transport, Outbox(outbox.path))
    try:
        assert resumed.wait_saved(5)
        assert outbox.stats()["cache_bytes"] == 0
        assert store.require_complete(spec.id)["count"] == 16
    finally:
        resumed.close()


def test_unavailable_pc_prevents_start(tmp_path):
    spec, store, transport, outbox, session = setup_capture(tmp_path)
    transport.online = False
    with pytest.raises(Unavailable):
        session.start()
    assert outbox.metadata("spec") is None
    assert store.recordings()["total"] == 0


def test_full_cache_ends_without_overwrite_or_auto_restart(tmp_path):
    spec, store, transport, outbox, session = setup_capture(tmp_path, max_bytes=5000)
    session.start()
    transport.online = False
    end = session.record(synthetic_packets(spec, 3), realtime=False)
    assert end.reason == "cache_full"
    count = outbox.stats()["produced"]
    assert count > 0
    transport.online = True
    try:
        assert session.wait_saved(5)
        assert store.require_complete(spec.id)["end"]["reason"] == "cache_full"
        assert outbox.stats()["produced"] == count
        assert store.recordings()["total"] == 1
    finally:
        session.close()


def test_idempotency_conflicts_late_packets_and_corruption(tmp_path):
    spec = synthetic_spec("rec", width=64, height=48, fps=2, imu_hz=4)
    store = Store(tmp_path, min_free_bytes=0)
    store.create(spec)
    packets = list(synthetic_packets(spec, 1))
    store.receive(packets[0])
    assert store.receive(packets[0]).sha256 == packets[0].digest()
    with pytest.raises(StoreError, match="different data"):
        store.receive(packets[0].model_copy(update={"source_timestamp_ns": 10}))
    assert store.end(spec.id, freeze(packets))["status"] == "awaiting_data"
    with pytest.raises(StoreError, match="incomplete"):
        store.require_complete(spec.id)
    for p in reversed(packets[1:]):
        store.receive(p)
    assert store.require_complete(spec.id)["status"] == "complete"
    with pytest.raises(StoreError, match="completed"):
        store.receive(packets[-1].model_copy(update={"sequence": len(packets)}))
    path = store.root / store.packet_rows(spec.id)[0]["path"]
    path.write_bytes(b"corrupted")
    assert store.verify(spec.id)["status"] == "integrity_failed"


def test_end_digest_and_start_metadata_conflicts(tmp_path):
    spec = synthetic_spec("rec", width=64, height=48)
    store = Store(tmp_path, min_free_bytes=0)
    store.create(spec)
    with pytest.raises(StoreError, match="different metadata"):
        store.create(spec.model_copy(update={"device_id": "other"}))
    packets = list(synthetic_packets(spec, 0.1))
    for p in packets:
        store.receive(p)
    wrong = freeze(packets).model_copy(update={"content_sha256": "0" * 64})
    assert store.end(spec.id, wrong)["status"] == "integrity_failed"
    with pytest.raises(StoreError, match="frozen"):
        store.end(spec.id, freeze(packets))


def test_api_auth_origin_and_validation(tmp_path):
    app = create_app(tmp_path, token="test-only-token")
    with TestClient(app) as client:
        assert client.get("/api/v1/ready").status_code == 401
        headers = {"Authorization": "Bearer test-only-token"}
        assert client.get("/api/v1/ready", headers=headers).status_code == 200
        assert (
            client.get(
                "/api/v1/ready", headers={**headers, "Origin": "https://other.example"}
            ).status_code
            == 403
        )
        response = client.post("/api/v1/recordings", headers=headers, json={"id": "../../bad"})
        assert response.status_code == 422
        assert "../../bad" not in response.text
        spec = synthetic_spec("api", width=64, height=48)
        assert (
            client.post("/api/v1/recordings", headers=headers, json=spec.model_dump()).status_code
            == 201
        )
        packet = next(synthetic_packets(spec, 0.1))
        assert (
            client.put(
                "/api/v1/recordings/api/packets/1", headers=headers, json=packet.model_dump()
            ).status_code
            == 422
        )
        response = client.put(
            "/api/v1/recordings/api/packets/0", headers=headers, json=packet.model_dump()
        )
        assert response.json()["durable"] is True
        assert (
            client.get("/api/v1/recordings/api/frames/0", headers=headers).headers["content-type"]
            == "image/jpeg"
        )


def test_wrong_ack_cannot_release_cache_and_end_keeps_last_sample(tmp_path):
    spec, store, transport, outbox, session = setup_capture(tmp_path)
    packet = next(synthetic_packets(spec, 0.1))
    outbox.put(packet)
    with pytest.raises(StoreError, match="exact packet"):
        outbox.acknowledge(
            packet, PacketAck(recording_id=spec.id, sequence=packet.sequence, sha256="0" * 64)
        )
    assert outbox.stats()["pending"] == 1
    end = outbox.freeze("user")
    assert end.ended_at_ns > packet.timestamp_ns


def test_metadata_tampering_blocks_completion(tmp_path):
    spec = synthetic_spec("metadata", width=64, height=48)
    store = Store(tmp_path, min_free_bytes=0)
    store.create(spec)
    packets = list(synthetic_packets(spec, 0.1))
    for p in packets:
        store.receive(p)
    store.end(spec.id, freeze(packets))
    (tmp_path / "recordings" / spec.id / "recording.json").write_text("{}")
    assert store.verify(spec.id)["status"] == "integrity_failed"
