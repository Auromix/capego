"""Download three bounded public EgoDex pairs with HTTP Range, not the whole ZIP.

Dataset terms: CC-BY-NC-ND, separate from CapEgo's Apache-2.0 code.
Downloaded data and derivatives stay local. Test-split clips are integration
fixtures only: never use these smoke-test updates for benchmark evaluation.
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import httpx

from capego.importers.egodex import file_digest

URL = "https://ml-site.cdn-apple.com/datasets/egodex/test.zip"
SAMPLES = ["test/add_remove_lid/0", "test/screw_unscrew_bottle_cap/0", "test/basic_fold/0"]


class RemoteZip(io.RawIOBase):
    def __init__(self, url=URL):
        self.client = httpx.Client(timeout=90, follow_redirects=True)
        self.url, self.position = url, 0
        response = self.client.head(url)
        response.raise_for_status()
        self.size = int(response.headers["content-length"])
        self.etag = response.headers.get("etag")
        self.downloaded = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        origins = {0: 0, 1: self.position, 2: self.size}
        if whence not in origins or origins[whence] + offset < 0:
            raise ValueError("Invalid ZIP offset")
        self.position = origins[whence] + offset
        return self.position

    def read(self, size=-1):
        size = max(0, min(self.size - self.position, size if size >= 0 else self.size))
        if not size:
            return b""
        if size > 128 * 1024**2:
            raise ValueError("Refusing an oversized range request")
        headers = {
            "Range": f"bytes={self.position}-{self.position + size - 1}",
            "Accept-Encoding": "identity",
        }
        if self.etag:
            headers["If-Match"] = self.etag
        with self.client.stream("GET", self.url, headers=headers) as response:
            response.raise_for_status()
            expected = f"bytes {self.position}-{self.position + size - 1}/{self.size}"
            if response.status_code != 206 or response.headers.get("content-range") != expected:
                raise ValueError(
                    "Server must honor the exact bounded Range; full downloads are rejected"
                )
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > size:
                    raise ValueError("Oversized range response")
        if len(data) != size:
            raise ValueError("Truncated range response")
        self.position += size
        self.downloaded += size
        return bytes(data)

    def close(self):
        self.client.close()
        super().close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runtime/real-data"))
    args = parser.parse_args()
    files = []
    with RemoteZip() as remote, zipfile.ZipFile(remote) as archive:
        for sample in SAMPLES:
            for ext in (".mp4", ".hdf5"):
                member = sample + ext
                info = archive.getinfo(member)
                if max(info.file_size, info.compress_size) > 64 * 1024**2:
                    raise ValueError("Sample exceeds download budget")
                path = args.output / member  # fixed allowlisted paths; no extractall
                path.parent.mkdir(parents=True, exist_ok=True)
                body = archive.read(info)  # verifies ZIP CRC
                path.write_bytes(body)
                files.append({"path": member, "bytes": len(body), "sha256": file_digest(path)})
                print(f"Downloaded {member}: {len(body)} bytes", flush=True)
        manifest = {
            "source_url": URL,
            "archive_etag": remote.etag,
            "archive_bytes": remote.size,
            "downloaded_bytes": remote.downloaded,
            "license": "CC-BY-NC-ND; see upstream terms",
            "purpose": "local integration smoke test; no redistribution or benchmark evaluation",
            "files": files,
        }
    (args.output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
