import json, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud.processor import run_from_bucket
from cloud.store import ObjectStore
from cloud.web import session_key_for
from test_cloud_store import FakeClient
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
NAME = "hoops__20260731-070000.m4a"
GOOD = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3), ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)]

class FakeTranscriber:
    model_id = "fake"
    def transcribe(self, path, prompt):
        return make_env(GOOD, duration=30.0)["response"]

@pytest.fixture
def rig(tmp_path, monkeypatch):
    # never reach real APIs even with email=True
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr("hoops.mailer.send", lambda msg, cfg: sent.append(msg))
    # cloud/config.cloud.yaml has gap_repair.enabled: true (production default); avoid a
    # real librosa decode in this offline unit test by stubbing the clip extraction step.
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    store = ObjectStore(FakeClient(), "hoops-data")
    store.put_bytes(f"raw/{NAME}", (REPO / "fixtures" / "dev" / "dev03.m4a").read_bytes())
    return store, sent, tmp_path

def test_ok_session_uploaded_and_raw_deleted(rig):
    store, sent, scratch = rig
    status = run_from_bucket(NAME, store, FakeTranscriber(), scratch)
    assert status == "ok"
    assert store.exists(session_key_for(NAME))                       # session.json in bucket
    keys = store.list_keys("sessions/2026/07/hoops__20260731-070000/")
    names = {k.rsplit("/", 1)[1] for k in keys}
    assert {"session.json", "shots.csv", "transcript.json", "transcript.txt",
            "report.html", "strip.png", "audio.m4a"} <= names
    assert not store.exists(f"raw/{NAME}")                           # transient raw cleaned
    assert len(sent) == 1                                            # email went out once

def test_zero_call_goes_to_needs_review_prefix(rig, monkeypatch):
    store, sent, scratch = rig
    class Chatty:
        model_id = "fake"
        def transcribe(self, path, prompt):
            return make_env([("just", 1.0, 1.2), ("talking", 1.3, 1.6)], duration=30.0)["response"]
    status = run_from_bucket(NAME, store, Chatty(), scratch)
    assert status == "needs_review"
    assert any(k.startswith("needs_review/") for k in store.list_keys("needs_review/"))
    assert not store.exists(f"raw/{NAME}")

def test_duplicate_in_bucket_short_circuits(rig):
    store, sent, scratch = rig
    store.put_bytes(session_key_for(NAME), b"{}")
    status = run_from_bucket(NAME, store, FakeTranscriber(), scratch)
    assert status == "duplicate"
    assert not store.exists(f"raw/{NAME}")                           # raw still drained
    assert len(sent) == 0

def test_missing_raw_raises(rig):
    store, sent, scratch = rig
    store.delete(f"raw/{NAME}")
    with pytest.raises(Exception):
        run_from_bucket(NAME, store, FakeTranscriber(), scratch)

def test_email_failure_raises_and_keeps_raw(rig, monkeypatch):
    store, sent, scratch = rig

    def boom(msg, cfg):
        raise RuntimeError("smtp down")
    monkeypatch.setattr("hoops.mailer.send", boom)

    with pytest.raises(RuntimeError, match="email send failed"):
        run_from_bucket(NAME, store, FakeTranscriber(), scratch)

    assert store.exists(f"raw/{NAME}")                  # raw retained for Modal retry
    assert store.list_keys("sessions/") == []            # marker never uploaded

def test_session_json_uploaded_last(rig):
    store, sent, scratch = rig
    status = run_from_bucket(NAME, store, FakeTranscriber(), scratch)
    assert status == "ok"
    keys = [k for (b, k) in store.client.blobs if k.startswith("sessions/")]
    assert keys[-1].endswith("/session.json")

def test_unexpected_outcome_raises_and_keeps_raw(rig, monkeypatch):
    import types
    store, sent, scratch = rig

    def fake_process_file(*a, **k):
        return types.SimpleNamespace(status="needs_review", session_dir=None, sid="x")
    monkeypatch.setattr("cloud.processor.process_file", fake_process_file)

    with pytest.raises(RuntimeError, match="unexpected outcome"):
        run_from_bucket(NAME, store, FakeTranscriber(), scratch)

    assert store.exists(f"raw/{NAME}")
