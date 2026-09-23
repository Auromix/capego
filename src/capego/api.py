"""Versioned local/LAN receiver API and offline workbench."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .contracts import EndRecording, Packet, RecordingSpec
from .storage import Store, StoreError


def create_app(root: str | Path, token: str | None = None, allowed_hosts=None) -> FastAPI:
    store = Store(root)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if getattr(app.state, "processor", None):
            app.state.processor.close()

    app = FastAPI(title="CapEgo", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def access(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if token and not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
                return JSONResponse({"error": {"code": "unauthorized", "message": "Receiver token required"}}, status_code=401)
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"error": {"code": "origin_rejected", "message": "Cross-origin API access is disabled"}}, status_code=403)
            if int(request.headers.get("content-length", "0")) > 16 * 1024**2:
                return JSONResponse({"error": {"code": "body_too_large", "message": "Packet exceeds receiver limit"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo raw request bodies (which may include frames or credentials).
        return JSONResponse({"error": {"code": "validation_error", "message": "Request does not match the API contract",
                                      "fields": [".".join(map(str, item["loc"])) for item in exc.errors()]}}, status_code=422)

    @app.get("/health")
    def health():
        return {"service": "capego", "version": "0.1.0"}

    @app.get("/api/v1/ready")
    def ready():
        return store.ready()

    @app.post("/api/v1/recordings", status_code=201)
    def create(spec: RecordingSpec):
        return store.create(spec)

    @app.get("/api/v1/recordings")
    def recordings(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        return store.recordings(limit, offset)

    @app.get("/api/v1/recordings/{recording_id}")
    def recording(recording_id: str):
        return store.recording(recording_id)

    @app.put("/api/v1/recordings/{recording_id}/packets/{sequence}")
    def receive(recording_id: str, sequence: int, packet: Packet):
        if packet.recording_id != recording_id or packet.sequence != sequence:
            raise StoreError("packet_identity_mismatch", "URL and packet identity differ", 422)
        return store.receive(packet)

    @app.put("/api/v1/recordings/{recording_id}/end")
    def end_recording(recording_id: str, end: EndRecording):
        return store.end(recording_id, end)

    @app.post("/api/v1/recordings/{recording_id}/verification")
    def verify(recording_id: str):
        return store.verify(recording_id)

    @app.get("/api/v1/recordings/{recording_id}/frames/{sequence}")
    def frame(recording_id: str, sequence: int):
        rows = store.packet_rows(recording_id)
        row = next((r for r in rows if r["sequence"] == sequence), None)
        if not row:
            raise StoreError("not_found", "Frame not found", 404)
        packet = store.read_packet(row)
        if packet.codec not in {"jpeg", "png"}:
            raise StoreError("not_image", "Packet is not an image", 422)
        return Response(packet.payload(), media_type=f"image/{packet.codec}")

    @app.get("/api/v1/recordings/{recording_id}/timeline")
    def timeline(recording_id: str, limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)):
        rows = store.packet_rows(recording_id)
        return {"items": [{k: r[k] for k in ("sequence", "stream_id", "timestamp_ns", "sha256")} for r in rows[offset:offset+limit]],
                "total": len(rows), "limit": limit, "offset": offset}

    @app.get("/")
    def workbench():
        path = Path(__file__).parent / "static" / "index.html"
        if not path.is_file():
            return {"service": "CapEgo", "docs": "/docs"}
        return FileResponse(path)

    return app
