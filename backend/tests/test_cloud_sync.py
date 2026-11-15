import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app import main
from app import cloud_sync
from app.sync_service import create_sync_bundle


PASSWORD = "cloud-sync-passphrase-2026"


def _configure_cloud(monkeypatch):
    monkeypatch.setattr(main.settings, "cloud_sync_enabled", True)
    monkeypatch.setattr(main.settings, "cloud_sync_provider", "webdav")
    monkeypatch.setattr(main.settings, "cloud_sync_url", "https://dav.example.test/remote.php/dav/files/user")
    monkeypatch.setattr(main.settings, "cloud_sync_username", "user")
    monkeypatch.setattr(main.settings, "cloud_sync_password", "password")


def test_cloud_sync_requires_confirmation_and_transfers_only_encrypted_bundle(monkeypatch, client):
    _configure_cloud(monkeypatch)
    uploaded = []

    class FakeProvider:
        def upload(self, bundle):
            uploaded.append(bundle)
            return {"status": "uploaded", "remote_url": "https://dav.example.test/sync.json"}

    monkeypatch.setattr(main, "WebDavSyncProvider", FakeProvider)
    preview = client.post("/api/sync/cloud/push", json={"passphrase": PASSWORD, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert uploaded == []

    applied = client.post("/api/sync/cloud/push", json={"passphrase": PASSWORD, "confirmed": True})
    assert applied.status_code == 200
    assert applied.json()["uploaded"] is True
    assert len(uploaded) == 1
    assert "跨设备" not in str(uploaded[0])


def test_cloud_pull_previews_then_appends_remote_data(monkeypatch, client):
    _configure_cloud(monkeypatch)
    remote_bundle = create_sync_bundle({"goals": [{"id": 701, "title": "云端目标", "description": "远端", "priority": 3, "status": "active"}]}, PASSWORD, {"goals": 1})

    class FakeProvider:
        def download(self):
            return remote_bundle

    monkeypatch.setattr(main, "WebDavSyncProvider", FakeProvider)
    preview = client.post("/api/sync/cloud/pull", json={"passphrase": PASSWORD, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert client.get("/api/goals").json() == []

    applied = client.post("/api/sync/cloud/pull", json={"passphrase": PASSWORD, "confirmed": True})
    assert applied.status_code == 200
    assert applied.json()["sync_applied"] is True
    assert client.get("/api/goals").json()[0]["title"] == "云端目标"


def test_webdav_provider_uses_json_put_and_get_without_following_redirects(monkeypatch):
    class Response:
        status_code = 200
        content = b'{"format":"learning-workstation-sync-v1"}'

        def json(self):
            return {"format": "learning-workstation-sync-v1"}

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.put_calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, **kwargs):
            self.put_calls.append((url, kwargs))
            return Response()

        def get(self, url, **kwargs):
            return Response()

    fake = Client()
    client_kwargs = []

    def client_factory(**kwargs):
        client_kwargs.append(kwargs)
        return fake

    monkeypatch.setattr(cloud_sync.httpx, "Client", client_factory)
    provider = cloud_sync.WebDavSyncProvider("https://dav.example.test/base", "u", "p", "folder/sync.json", 3)
    assert provider.upload({"format": "learning-workstation-sync-v1"})["status"] == "uploaded"
    assert provider.download()["format"] == "learning-workstation-sync-v1"
    assert fake.put_calls[0][1]["headers"]["Content-Type"] == "application/json"
    assert client_kwargs[0]["follow_redirects"] is False
    assert client_kwargs[0]["trust_env"] is False


def test_webdav_provider_rejects_path_traversal_and_empty_segments():
    for path in ("folder/../sync.json", "../sync.json", "folder//sync.json", "folder/./sync.json"):
        provider = cloud_sync.WebDavSyncProvider("https://dav.example.test/base", "u", "p", path, 3)
        try:
            _ = provider.resource_url
        except cloud_sync.CloudSyncError:
            continue
        raise AssertionError(f"unsafe WebDAV path was accepted: {path}")


def test_webdav_provider_rejects_unsafe_base_urls_and_oversized_upload(monkeypatch):
    for base_url in (
        "ftp://dav.example.test/base",
        "https://user:password@dav.example.test/base",
        "https://dav.example.test/base?token=secret",
        "https://dav.example.test/base/../other",
    ):
        provider = cloud_sync.WebDavSyncProvider(base_url, "u", "p", "sync.json", 3)
        try:
            _ = provider.resource_url
        except cloud_sync.CloudSyncError:
            continue
        raise AssertionError(f"unsafe WebDAV base URL was accepted: {base_url}")

    monkeypatch.setattr(cloud_sync.settings, "max_request_body_bytes", 8)
    provider = cloud_sync.WebDavSyncProvider("https://dav.example.test/base", "u", "p", "sync.json", 3)
    try:
        provider.upload({"payload": "too large"})
    except cloud_sync.CloudSyncError as exc:
        assert "请求体" in str(exc)
    else:
        raise AssertionError("oversized WebDAV upload was accepted")


def test_webdav_provider_round_trips_against_local_http_server():
    stored = {}
    expected_auth = "Basic " + base64.b64encode(b"user:password").decode("ascii")

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self):
            return self.headers.get("Authorization") == expected_auth

        def do_PUT(self):  # noqa: N802
            if not self._authorized():
                self.send_response(401)
                self.end_headers()
                return
            stored[self.path] = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(201)
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if not self._authorized():
                self.send_response(401)
                self.end_headers()
                return
            payload = stored.get(self.path)
            if payload is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = cloud_sync.WebDavSyncProvider(f"http://127.0.0.1:{server.server_port}", "user", "password", "sync.json", 3)
        bundle = {"format": "learning-workstation-sync-v1", "ciphertext": "encrypted"}
        assert provider.upload(bundle)["status"] == "uploaded"
        assert provider.download() == bundle
        assert json.loads(next(iter(stored.values()))) == bundle
    finally:
        server.shutdown()
        thread.join(timeout=2)
