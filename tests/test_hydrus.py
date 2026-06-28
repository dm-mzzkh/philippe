"""HydrusClient unit tests (pure Python, no network)."""

import json
from hashlib import sha256
from io import BytesIO

import pytest

from philippe._hydrus import HydrusClient, HydrusError


class FakeHTTPHandler:
    """Mocks urllib.request.urlopen for controlled HTTP responses."""
    def __init__(self):
        self.handlers: dict[str, callable] = {}
        self.requests: list = []

    def add(self, method: str, path_prefix: str, response: bytes, status: int = 200):
        key = (method, path_prefix)
        self.handlers[key] = (lambda req, key=key: (status, response))

    def __call__(self, req):
        self.requests.append((req.method, req.full_url, req.data))
        for (method, prefix), handler in self.handlers.items():
            if req.method == method and prefix in req.full_url:
                status, body = handler(req)
                return _fake_response(status, body)
        raise _http_error(404, "Not Found")


def _fake_response(status: int, body: bytes):
    return type("R", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None,
                           "status": status, "read": lambda s=None: body})()


def _http_error(code: int, reason: str):
    from urllib.error import HTTPError
    return HTTPError("http://fake", code, reason, {}, BytesIO(b""))


def test_upload_returns_sha256_hash(monkeypatch):
    blob = b"hello hydrus"
    expected_hash = sha256(blob).hexdigest()

    handler = FakeHTTPHandler()
    handler.add("POST", "/add_files/add_file",
                json.dumps({"status": 1, "hash": expected_hash}).encode())
    monkeypatch.setattr("urllib.request.urlopen", handler)

    client = HydrusClient("http://fake:45869", "key123")
    assert client.upload(blob) == expected_hash

    req = handler.requests[0]
    assert req[0] == "POST" and "/add_files/add_file" in req[1]
    assert req[2] == blob  # raw bytes body


def test_download_returns_blob(monkeypatch):
    blob = b"stored data"
    handler = FakeHTTPHandler()
    handler.add("GET", "/get_files/file", blob)
    monkeypatch.setattr("urllib.request.urlopen", handler)

    client = HydrusClient("http://fake:45869", "key123")
    assert client.download("abcdef") == blob


def test_upload_http_error_raises_hydrus_error(monkeypatch):
    def _fail(req):
        raise _http_error(500, "Internal Server Error")

    monkeypatch.setattr("urllib.request.urlopen", _fail)
    client = HydrusClient("http://fake:45869", "key123")
    with pytest.raises(HydrusError, match="HTTP 500"):
        client.upload(b"boom")


def test_tag_fetches_service_key_once(monkeypatch):
    handler = FakeHTTPHandler()
    handler.add("GET", "/get_services",
                json.dumps({"tag_services": [
                    {"name": "my tags", "service_key": "sk:my-tags"},
                ]}).encode())
    handler.add("POST", "/add_tags/add_tags", b"{}")
    monkeypatch.setattr("urllib.request.urlopen", handler)

    client = HydrusClient("http://fake:45869", "key123")
    client.tag("hash1", ["t1"])

    # First request = get_services, second = add_tags
    assert len(handler.requests) == 2
    assert "get_services" in handler.requests[0][1]
    tag_req = handler.requests[1]
    body = json.loads(tag_req[2])
    assert body["hash"] == "hash1"
    assert body["service_keys_to_tags"]["sk:my-tags"] == ["t1"]

    # Tag another file — uses cached key (no second get_services call)
    client.tag("hash2", ["t2"])
    assert len(handler.requests) == 3
    assert "get_services" not in handler.requests[2][1]


def test_tag_service_not_found_raises(monkeypatch):
    handler = FakeHTTPHandler()
    handler.add("GET", "/get_services",
                json.dumps({"tag_services": []}).encode())
    monkeypatch.setattr("urllib.request.urlopen", handler)

    client = HydrusClient("http://fake:45869", "key123")
    with pytest.raises(HydrusError, match="could not find"):
        client.tag("hash1", ["t1"])
