import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root for cloud/
from cloud.store import ObjectStore

pytestmark = pytest.mark.unit

class FakeClient:
    """Records boto3-style calls; raises the shapes ObjectStore must handle."""
    def __init__(self):
        self.blobs = {}
    def put_object(self, Bucket, Key, Body):
        self.blobs[(Bucket, Key)] = Body
    def get_object(self, Bucket, Key):
        import io
        if (Bucket, Key) not in self.blobs:
            raise self.exceptions.NoSuchKey({}, "GetObject")
        return {"Body": io.BytesIO(self.blobs[(Bucket, Key)])}
    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.blobs:
            err = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}
            from botocore.exceptions import ClientError
            raise ClientError(err, "HeadObject")
        return {}
    def list_objects_v2(self, Bucket, Prefix):
        keys = [k for (b, k) in self.blobs if b == Bucket and k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}
    def delete_object(self, Bucket, Key):
        self.blobs.pop((Bucket, Key), None)
    class exceptions:
        class NoSuchKey(Exception):
            def __init__(self, *a): pass

@pytest.fixture
def store():
    return ObjectStore(FakeClient(), "hoops-data")

def test_put_get_roundtrip(store):
    store.put_bytes("raw/x.m4a", b"abc")
    assert store.get_bytes("raw/x.m4a") == b"abc"

def test_exists_true_false(store):
    assert not store.exists("sessions/2026/07/hoops__x/session.json")
    store.put_bytes("sessions/2026/07/hoops__x/session.json", b"{}")
    assert store.exists("sessions/2026/07/hoops__x/session.json")

def test_list_keys_prefix(store):
    store.put_bytes("sessions/a/1", b"1"); store.put_bytes("sessions/a/2", b"2")
    store.put_bytes("raw/other", b"x")
    assert sorted(store.list_keys("sessions/a/")) == ["sessions/a/1", "sessions/a/2"]
    assert store.list_keys("nope/") == []

def test_delete(store):
    store.put_bytes("raw/x", b"1"); store.delete("raw/x")
    assert not store.exists("raw/x")

def test_from_env_builds_client(monkeypatch):
    calls = {}
    import cloud.store as cs
    def fake_client(kind, endpoint_url, aws_access_key_id, aws_secret_access_key, region_name):
        calls.update(kind=kind, endpoint=endpoint_url, key=aws_access_key_id)
        return FakeClient()
    monkeypatch.setattr(cs.boto3, "client", fake_client)
    for k, v in [("R2_ENDPOINT", "https://x.r2.cloudflarestorage.com"),
                 ("R2_ACCESS_KEY_ID", "id"), ("R2_SECRET_ACCESS_KEY", "sk"),
                 ("R2_BUCKET", "hoops-data")]:
        monkeypatch.setenv(k, v)
    s = ObjectStore.from_env()
    assert calls == {"kind": "s3", "endpoint": "https://x.r2.cloudflarestorage.com", "key": "id"}
    assert s.bucket == "hoops-data"
