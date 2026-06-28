"""Hydrus Network client — upload, download, tag files via the Client API."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger("philippe.hydrus")


class HydrusError(Exception):
    pass


class HydrusClient:
    def __init__(self, url: str, key: str) -> None:
        self._url = url.rstrip("/")
        self._key = key
        self._cached_tag_service: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
    ) -> tuple[int, bytes]:
        url = f"{self._url}{path}"
        req_headers = {"Hydrus-Client-API-Access-Key": self._key}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=body, headers=req_headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            raise HydrusError(
                f"hydrus {method} {path}: HTTP {e.code} {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise HydrusError(f"hydrus {method} {path}: {e.reason}") from e

    def upload(self, blob: bytes) -> str:
        """Upload raw bytes. Returns the SHA-256 hex hash."""
        _, resp = self._request(
            "POST", "/add_files/add_file", body=blob,
            headers={"Content-Type": "application/octet-stream"},
        )
        data = json.loads(resp)
        if data.get("status") not in (1, 2):
            raise HydrusError(f"upload failed: {data}")
        return str(data["hash"])

    def thumbnail(self, file_hash: str) -> bytes:
        """Download thumbnail by SHA-256 hash."""
        _, data = self._request(
            "GET", f"/get_files/thumbnail?hash={file_hash}",
        )
        return bytes(data)

    def download(self, file_hash: str) -> bytes:
        """Download file by SHA-256 hash."""
        _, data = self._request(
            "GET", f"/get_files/file?hash={file_hash}",
        )
        return bytes(data)

    def tag(self, file_hash: str, tags: list[str]) -> None:
        """Apply tags to a file on the local 'my tags' service."""
        sk = self._tag_service_key
        body = json.dumps({"hash": file_hash,
                           "service_keys_to_tags": {sk: tags}}).encode()
        self._request("POST", "/add_tags/add_tags", body=body,
                      headers={"Content-Type": "application/json"})

    @property
    def _tag_service_key(self) -> str:
        if self._cached_tag_service is None:
            _, resp = self._request("GET", "/get_services")
            services = json.loads(resp)
            for s in services.get("tag_services", []):
                if s.get("name") == "my tags":
                    self._cached_tag_service = s["service_key"]
                    break
            if self._cached_tag_service is None:
                raise HydrusError("could not find 'my tags' tag service")
        return self._cached_tag_service
