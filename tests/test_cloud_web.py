import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud.web import make_app, session_key_for
from test_cloud_store import FakeClient
from cloud.store import ObjectStore

pytestmark = pytest.mark.unit
KEY = "test-secret"
GOOD = "hoops__20260731-070000.m4a"

@pytest.fixture
def rig():
    store = ObjectStore(FakeClient(), "hoops-data")
    spawned = []
    app = make_app(store, spawned.append, KEY)
    return TestClient(app), store, spawned

def post(client, filename=GOOD, key=KEY, data=b"fake-audio"):
    headers = {"X-Hoops-Key": key} if key is not None else {}
    return client.post("/upload", headers=headers,
                       files={"file": (filename, data, "audio/mp4")})

def test_session_key_for():
    assert session_key_for(GOOD) == "sessions/2026/07/hoops__20260731-070000/session.json"

def test_happy_path_stores_and_spawns(rig):
    client, store, spawned = rig
    r = post(client)
    assert r.status_code == 200
    assert r.json() == {"status": "processing", "sid": "20260731-070000"}
    assert store.get_bytes(f"raw/{GOOD}") == b"fake-audio"
    assert spawned == [GOOD]

def test_wrong_key_401_nothing_written(rig):
    client, store, spawned = rig
    assert post(client, key="nope").status_code == 401
    assert post(client, key=None).status_code in (401, 422)
    assert store.list_keys("raw/") == [] and spawned == []

def test_bad_filename_400(rig):
    client, store, spawned = rig
    for bad in ["food__x.m4a", "hoops_20260731-070000.m4a", "hoops__2026.m4a",
                "../evil.m4a", "hoops__20260731-070000.mp3"]:
        assert post(client, filename=bad).status_code == 400, bad
    assert store.list_keys("raw/") == [] and spawned == []

def test_duplicate_sid_acks_without_spawn(rig):
    client, store, spawned = rig
    store.put_bytes(session_key_for(GOOD), b"{}")
    r = post(client)
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    assert spawned == [] and store.list_keys("raw/") == []

def test_oversize_413(rig):
    client, store, spawned = rig
    r = post(client, data=b"x" * (64 * 1024 * 1024 + 1))
    assert r.status_code == 413
    assert store.list_keys("raw/") == [] and spawned == []
