# Cloud Pipeline (Modal + R2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phone POSTs a recording to a Modal endpoint; a stateless worker runs the existing pipeline and stores everything in an R2 bucket; the email arrives ~2 minutes later — Mac fully out of the data path, proven against the golden dataset.

**Architecture:** Three new cloud modules with a strict purity gradient: `cloud/store.py` (S3-compatible object store wrapper, testable), `cloud/web.py` (FastAPI app factory, pure, testable), `cloud/processor.py` (bucket→scratch→`process_file`→bucket, testable with fakes), and `cloud/modal_app.py` (thin Modal wiring of the three, not unit-tested). The pipeline core is untouched.

**Tech Stack:** Python 3.12; new optional deps (cloud extra): `modal`, `boto3`, `fastapi`, `python-multipart`; dev adds `httpx` (TestClient). Cloudflare R2 (S3 API). Gmail SMTP unchanged.

**Spec:** `docs/specs/2026-07-31-cloud-migration-design.md` — read it first.

## Global Constraints

- Pipeline core untouched: no changes to `parse.py`/`stats.py`/`invariants.py`/`pipeline.py`/`report_html.py` (if a hidden path assumption in `pipeline.py` surfaces, STOP and report — don't patch silently).
- Cloud deps live in `[project.optional-dependencies] cloud = [...]` in `pyproject.toml`; core install stays lean. Dev deps may add `httpx` (and the cloud extras for tests).
- Unit tests never touch the network: no Modal, no real S3, no OpenAI/SMTP. `cloud/modal_app.py` is exempt from unit coverage (thin wiring); everything else is tested.
- Secrets only via env/`modal.Secret` (`OPENAI_API_KEY, ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD, HOOPS_UPLOAD_KEY, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET`). NEVER print or commit values.
- Bucket layout (exact prefixes): `raw/<filename>` (transient) · `sessions/YYYY/MM/hoops__<sid>/<artifact>` · `needs_review/<name>/<artifact>` · `rejected/<filename>`.
- Endpoint contract: header `X-Hoops-Key`; 401 wrong/missing key (nothing written); 400 filename not matching `hoops__\d{8}-\d{6}\.m4a`; 413 >64MB; 200 `{"status":"duplicate"}` when the sid's `session.json` already exists in the bucket; 200 `{"status":"processing","sid":...}` otherwise.
- All tests: `uv run pytest` from repo root. Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Branch `feat/cloud-pipeline` (exists, spec at d1ad3f4).
- Owner-involved steps (account signup, secret values, phone Shortcut) are marked **[OWNER]** — pause and ask, never fake.

## Reference: existing shapes consumed

- `load_config(path) -> Config` (`src/hoops/config.py:49`): `repo_root` = config file's parent; relative `sessions_root` resolves under it; `process_file` writes `needs_review/`/`rejected/` under `repo_root`. So: copy a cloud config template into the scratch dir and load it from there — every output lands under scratch.
- `process_file(path, cfg, transcriber, *, email, archive="move", ...) -> Outcome` (`src/hoops/pipeline.py:96`): `Outcome.status` ∈ ok/needs_review/rejected/duplicate, `Outcome.session_dir`.
- `WhisperApiTranscriber(model)` (`src/hoops/transcribe.py:55`); CLI builds it as `WhisperApiTranscriber(cfg.transcriber_model)` (`cli.py:43`).
- Filename contract regex lives at `src/hoops/session.py` `_PREFIX_RE = ^hoops__(\d{8}-\d{6})\.m4a$` (case-insensitive) — import and reuse, don't re-invent.
- Test helper `make_env(words, duration)` in `tests/conftest.py`; fixture audio in `fixtures/*.m4a`; manifest baselines in `fixtures/manifest.csv` machine columns (`got_calls`).
- Manifest baseline note for the acceptance gate: local `got_calls` were produced from **cached transcripts** (`fixtures/transcripts/*.json`), so cloud re-transcription may differ slightly on hard fixtures; the gate's comparison rules handle this (Task 6).

---

### Task 1: `cloud/store.py` — object store wrapper

**Files:**
- Create: `cloud/store.py`, `cloud/__init__.py` (empty)
- Modify: `pyproject.toml` (add optional-dependencies `cloud` = ["modal>=1.0", "boto3>=1.34", "fastapi>=0.110", "python-multipart>=0.0.9"]; add `httpx>=0.27` to dev group; run `uv sync --extra cloud` once so dev env has them)
- Test: `tests/test_cloud_store.py`

**Interfaces:**
- Produces: `class ObjectStore` with `__init__(self, client, bucket: str)`, `put_bytes(key: str, data: bytes) -> None`, `get_bytes(key: str) -> bytes`, `exists(key: str) -> bool`, `list_keys(prefix: str) -> list[str]`, `delete(key: str) -> None`, and classmethod `from_env(cls) -> "ObjectStore"` (boto3 client from `R2_ENDPOINT`/`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`/`R2_BUCKET` env vars). Tasks 2-3 consume exactly these six methods.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cloud_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv sync --extra cloud && uv run pytest tests/test_cloud_store.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'cloud'` (or `cloud.store`).

- [ ] **Step 3: Implement `cloud/store.py`**

```python
"""S3-compatible object store wrapper — works against R2/B2/S3/Supabase.

The one reusable storage piece for every future capture tool: construct
from env, then put/get/list/delete by key. No hoops-specific logic here.
"""
import os
import boto3
from botocore.exceptions import ClientError

class ObjectStore:
    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_env(cls) -> "ObjectStore":
        client = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        return cls(client, os.environ["R2_BUCKET"])

    def put_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404 \
               or e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def list_keys(self, prefix: str) -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kw)
            out += [o["Key"] for o in resp.get("Contents", [])]
            token = resp.get("NextContinuationToken")
            if not token:
                return out

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
```

(FakeClient's `list_objects_v2` ignores pagination — fine: the loop exits when no `NextContinuationToken`.)

Create empty `cloud/__init__.py`.

In `pyproject.toml`, add (matching the file's existing style — read it first):
```toml
[project.optional-dependencies]
cloud = ["modal>=1.0", "boto3>=1.34", "fastapi>=0.110", "python-multipart>=0.0.9"]
```
and `httpx>=0.27` to the dev dependency group.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cloud_store.py -q` then full `uv run pytest -q`. Expected: green.

- [ ] **Step 5: Commit**

```bash
git add cloud/ tests/test_cloud_store.py pyproject.toml uv.lock
git commit -m "feat(cloud): S3-compatible ObjectStore wrapper + cloud extras

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `cloud/web.py` — upload endpoint app factory

**Files:**
- Create: `cloud/web.py`
- Test: `tests/test_cloud_web.py`

**Interfaces:**
- Consumes: `ObjectStore` (Task 1 methods), `hoops.session._PREFIX_RE`.
- Produces: `make_app(store, spawn, upload_key: str) -> FastAPI` where `spawn` is `Callable[[str], None]` (called with the validated filename) — Task 4 passes `processor.spawn`. Also `session_key_for(filename: str) -> str` returning the bucket key of that sid's `session.json` (used for dedupe here and by Task 3's uploader; format `sessions/YYYY/MM/hoops__<sid>/session.json` derived from the sid exactly like `session.session_dir_for` does: `sid[:4]` year, `sid[4:6]` month).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cloud_web.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cloud_web.py -q`
Expected: `ModuleNotFoundError: No module named 'cloud.web'`.

- [ ] **Step 3: Implement `cloud/web.py`**

```python
"""Upload endpoint app factory. Pure FastAPI — no Modal imports — so it is
fully testable with TestClient and reusable for future capture tools."""
import hmac
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from hoops.session import _PREFIX_RE

MAX_BYTES = 64 * 1024 * 1024

def session_key_for(filename: str) -> str:
    sid = _PREFIX_RE.match(filename).group(1)
    return f"sessions/{sid[:4]}/{sid[4:6]}/hoops__{sid}/session.json"

def make_app(store, spawn, upload_key: str) -> FastAPI:
    app = FastAPI()

    @app.post("/upload")
    async def upload(file: UploadFile = File(...),
                     x_hoops_key: str = Header(default="")):
        if not hmac.compare_digest(x_hoops_key, upload_key):
            raise HTTPException(status_code=401, detail="bad key")
        name = file.filename or ""
        m = _PREFIX_RE.match(name)
        if not m:
            raise HTTPException(status_code=400,
                                detail="filename must be hoops__YYYYMMDD-HHMMSS.m4a")
        data = await file.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="recording too large")
        sid = m.group(1)
        if store.exists(session_key_for(name)):
            return {"status": "duplicate", "sid": sid}
        store.put_bytes(f"raw/{name}", data)
        spawn(name)
        return {"status": "processing", "sid": sid}

    return app
```

Note: `_PREFIX_RE` is imported from the existing contract (`src/hoops/session.py`) — the filename rules stay defined in exactly one place.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cloud_web.py -q` then full `uv run pytest -q`. Expected: green. (The oversize test allocates 64MB once — acceptable.)

- [ ] **Step 5: Commit**

```bash
git add cloud/web.py tests/test_cloud_web.py
git commit -m "feat(cloud): upload endpoint app factory — auth, contract validation, dedupe

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `cloud/processor.py` + `cloud/config.cloud.yaml` — bucket→pipeline→bucket

**Files:**
- Create: `cloud/processor.py`, `cloud/config.cloud.yaml`
- Test: `tests/test_cloud_processor.py`

**Interfaces:**
- Consumes: `ObjectStore`, `session_key_for`, `load_config`, `process_file`, `make_env` (tests).
- Produces: `run_from_bucket(name: str, store, transcriber, scratch: Path) -> str` — downloads `raw/<name>`, prepares scratch config, runs `process_file(..., email=True, archive="move")`, uploads every outcome file to the matching bucket prefix, deletes `raw/<name>`, returns `Outcome.status`. Raises on pipeline exceptions (Modal retry/alerting handles them — Task 4).

- [ ] **Step 1: Write `cloud/config.cloud.yaml`**

Copy `config.yaml` and change ONLY these keys (everything else — vocabularies, isolation, limits, transcriber, llm, email, profanity — stays byte-identical; read the real file first):

```yaml
inbox: inbox            # unused in cloud mode; kept for Config completeness
sessions_root: sessions # resolves under the scratch dir the template is copied into
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_cloud_processor.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cloud_processor.py -q`
Expected: `ModuleNotFoundError: No module named 'cloud.processor'`.

- [ ] **Step 4: Implement `cloud/processor.py`**

```python
"""Stateless worker: bucket -> scratch -> existing pipeline -> bucket.

The bucket is the source of truth; this process owns nothing durable.
"""
import shutil
from pathlib import Path
from hoops.config import load_config
from hoops.pipeline import process_file
from .web import session_key_for

_TEMPLATE = Path(__file__).parent / "config.cloud.yaml"

def _upload_dir(store, local_dir: Path, key_prefix: str) -> None:
    for f in sorted(local_dir.rglob("*")):
        if f.is_file():
            store.put_bytes(f"{key_prefix}/{f.relative_to(local_dir)}", f.read_bytes())

def run_from_bucket(name: str, store, transcriber, scratch: Path) -> str:
    # duplicate guard (idempotent retries / racing spawns)
    if store.exists(session_key_for(name)):
        store.delete(f"raw/{name}")
        return "duplicate"

    work = scratch / "work"
    if work.exists():
        shutil.rmtree(work)
    (work / "inbox").mkdir(parents=True)
    shutil.copy(_TEMPLATE, work / "config.yaml")
    cfg = load_config(work / "config.yaml")        # repo_root == work

    audio = work / "inbox" / name
    audio.write_bytes(store.get_bytes(f"raw/{name}"))

    out = process_file(audio, cfg, transcriber, email=True, archive="move")

    if out.status in ("ok", "duplicate") and out.session_dir is not None:
        sid = out.sid
        _upload_dir(store, out.session_dir, f"sessions/{sid[:4]}/{sid[4:6]}/{out.session_dir.name}")
    elif out.status == "needs_review" and out.session_dir is not None:
        _upload_dir(store, out.session_dir, f"needs_review/{out.session_dir.name}")
    elif out.status == "rejected":
        rej = work / "rejected" / name
        if rej.exists():
            store.put_bytes(f"rejected/{name}", rej.read_bytes())

    store.delete(f"raw/{name}")
    return out.status
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cloud_processor.py -q` then full `uv run pytest -q`. Expected: green. (These tests exercise the REAL pipeline — transcribe faked, whisper prompt built, parse/stats/report all run — so they're the strongest local proof the cloud path works.)

- [ ] **Step 6: Commit**

```bash
git add cloud/processor.py cloud/config.cloud.yaml tests/test_cloud_processor.py
git commit -m "feat(cloud): stateless processor — bucket to pipeline to bucket

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `cloud/modal_app.py` — Modal wiring + deploy + smoke E2E **[OWNER involvement]**

**Files:**
- Create: `cloud/modal_app.py`
- No unit tests (thin wiring, exempt per Global Constraints); verification is a real deploy + smoke run.

**Interfaces:**
- Consumes: `make_app`, `run_from_bucket`, `ObjectStore.from_env`, `WhisperApiTranscriber`.
- Produces: deployed endpoint URL (recorded in the SDD ledger, NOT committed anywhere) and Modal function `processor`.

- [ ] **Step 1: Write `cloud/modal_app.py`**

```python
"""Modal wiring: `modal deploy cloud/modal_app.py`.

Everything testable lives in web.py/processor.py/store.py; this file only
binds them to Modal primitives (image, secrets, endpoint, spawn, retries).
"""
from pathlib import Path
import modal

app = modal.App("hoops")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("openai>=1.35", "anthropic>=0.40", "matplotlib>=3.9",
                 "mutagen>=1.47", "pyyaml>=6.0", "python-dotenv>=1.0",
                 "fastapi>=0.110", "python-multipart>=0.0.9", "boto3>=1.34")
    .add_local_python_source("hoops", "cloud")
    .add_local_file(Path(__file__).parent / "config.cloud.yaml",
                    "/root/cloud/config.cloud.yaml")
)
secrets = [modal.Secret.from_name("hoops-secrets")]

@app.function(image=image, secrets=secrets, timeout=600,
              retries=modal.Retries(max_retries=3, backoff_coefficient=2.0))
def processor(name: str) -> str:
    import tempfile, traceback, yaml
    from cloud.processor import run_from_bucket
    from cloud.store import ObjectStore
    from hoops.transcribe import WhisperApiTranscriber
    store = ObjectStore.from_env()
    try:
        with tempfile.TemporaryDirectory() as scratch:
            cfg_path = Path("/root/cloud/config.cloud.yaml")
            model = yaml.safe_load(cfg_path.read_text())["transcriber"]["model"]
            transcriber = WhisperApiTranscriber(model)
            return run_from_bucket(name, store, transcriber, Path(scratch))
    except Exception as e:
        _alert(name, f"{e!r}\n{traceback.format_exc()[-1500:]}")
        raise

def _alert(name: str, err: str) -> None:
    try:
        import os, smtplib
        from email.message import EmailMessage
        import yaml
        raw = yaml.safe_load(Path("/root/cloud/config.cloud.yaml").read_text())
        email = raw["email"]
        addr = os.environ.get("GMAIL_ADDRESS", "").strip() or email["from"]
        msg = EmailMessage()
        msg["From"], msg["To"] = addr, addr
        msg["Subject"] = f"⚠️ 🏀 cloud processing failed for {name}"
        msg.set_content(f"All retries exhausted.\n\n{err}")
        with smtplib.SMTP_SSL(email["smtp_host"], int(email["smtp_port"])) as s:
            s.login(addr, os.environ["GMAIL_APP_PASSWORD"])
            s.send_message(msg)
    except Exception:
        pass  # alerting is best-effort; Modal logs still capture everything

@app.function(image=image, secrets=secrets)
@modal.asgi_app()
def web():
    import os
    from cloud.web import make_app
    from cloud.store import ObjectStore
    return make_app(ObjectStore.from_env(),
                    lambda name: processor.spawn(name),
                    os.environ["HOOPS_UPLOAD_KEY"])

@app.local_entrypoint()
def pull_sessions(dest: str = "sessions"):
    """modal run cloud/modal_app.py::pull_sessions — sync bucket sessions -> local."""
    import os
    from cloud.store import ObjectStore
    store = ObjectStore.from_env()
    n = 0
    for key in store.list_keys("sessions/"):
        target = Path(dest) / Path(key).relative_to("sessions")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(store.get_bytes(key))
            n += 1
    print(f"pulled {n} new file(s) into {dest}/")
```

Note: the transcriber model is read from the shipped `config.cloud.yaml` — hard-coding `"whisper-1"` anywhere in `cloud/` is forbidden (the reviewer should grep for it).
`pull_sessions` runs locally (`local_entrypoint`), so it needs the R2 env vars in the local shell — document: `set -a; source .env.r2; set +a` where `.env.r2` is a NEW gitignored file the owner creates in Step 2 (add `.env.r2` to `.gitignore` in this task).

- [ ] **Step 2 [OWNER]: Accounts + secrets**

Pause and walk the owner through, never printing secret values:
1. Modal: `uv run modal setup` (browser auth — suggest the owner runs `! uv run modal setup` so the interactive flow lands in-session).
2. Cloudflare R2: create account/bucket `hoops-data`, generate S3 API token. **Verify here whether R2 activation required a card** (spec's open item); if the owner objects, fall back to Backblaze B2 (same S3 API — only `R2_ENDPOINT` differs) and record the decision in the ledger + spec.
3. `.env.r2` locally (gitignored) with the four R2 vars for `pull_sessions`.
4. Create the Modal secret (values typed by owner or sourced from `.env`/`.env.r2` WITHOUT echoing):
   `uv run modal secret create hoops-secrets OPENAI_API_KEY=... ANTHROPIC_API_KEY=... GMAIL_APP_PASSWORD=... GMAIL_ADDRESS=... HOOPS_UPLOAD_KEY=... R2_ENDPOINT=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=hoops-data`
   (`HOOPS_UPLOAD_KEY`: generate with `openssl rand -hex 24`; the owner also puts it in the phone Shortcut later.)

- [ ] **Step 3: Deploy + smoke E2E (real APIs, ~2¢)**

```bash
uv run modal deploy cloud/modal_app.py           # prints the web endpoint URL
curl -sf -X POST "<URL>/upload" -H "X-Hoops-Key: $HOOPS_UPLOAD_KEY" \
     -F "file=@fixtures/F01_NormalSwishBrick.m4a;filename=hoops__20990101-000001.m4a" | tee /dev/stderr
```
Verify: ack JSON → Modal dashboard/logs show the processor run → email arrives (fixture will flag invariants — expected) → `modal run cloud/modal_app.py::pull_sessions --dest /tmp/pull-test` fetches the session. Also verify the negative contract live: wrong key → 401; bad filename → 400; re-POST same filename → `duplicate`. This smoke run doubles as the **Modal request-body ceiling check** (2.7MB fixture through the endpoint); test a larger body by re-posting `sessions/.../audio.m4a`-sized files only if the 2.7MB behaves oddly.
Delete the test session from R2 (`raw/` should already be empty) and `/tmp/pull-test`.

- [ ] **Step 4: Commit**

```bash
git add cloud/modal_app.py .gitignore
git commit -m "feat(cloud): Modal app — endpoint, worker with retries+alerting, pull_sessions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Docs, Shortcut section, decommission **[OWNER involvement]**

**Files:**
- Modify: `docs/shortcut-setup.md` (cloud upload section), `docs/architecture.md` (cloud topology as primary, local mode as fallback), `CLAUDE.md` (status + read-first + rules; same-change rule), `docs/playbook.md` (one worked-example line in §6 about moving compute to where data can't be evicted), `README.md` (How it works diagram gains the cloud path)

- [ ] **Step 1: Docs edits**

- `shortcut-setup.md`: new "Cloud upload (current)" section — replace the Save File step with **Get Contents of URL**: URL `<endpoint>/upload`, Method POST, Request Body = Form, form field `file` = the renamed recording (the existing Set Name + Formatted Date steps are unchanged), Header `X-Hoops-Key` = the secret. Note the instant "processing" ack and ~2-minute email. Keep the iCloud steps under "Local mode (fallback)".
- `architecture.md`: swap the ingestion narrative — the four-box cloud diagram (endpoint → R2 → worker → email) becomes primary; the launchd/iCloud section becomes "Local fallback mode"; failure handling updated (Modal retries ×3 → alert email; logs in the dashboard; raw/ retained on failure for manual replay).
- `CLAUDE.md`: status bullet (cloud pipeline live, endpoint on Modal, data lake in R2, Mac = dev loop + `pull_sessions`); Development rules add: "cloud changes: `uv run pytest` then `modal deploy`; unit tests never touch the network"; pending work drops nothing.
- `playbook.md` §6 gains: "When local infra fights the data (iCloud evicted sessions mid-pipeline), I moved compute to the cloud rather than adding workarounds — see `docs/specs/2026-07-31-cloud-migration-design.md`."
- `README.md`: update the "How it works" flow to phone → endpoint → R2 → email, with local mode noted.

- [ ] **Step 2: Run link-check + suite**

Reuse the Task-4-style link check from the golden-template plan over the touched docs; `uv run pytest -q`.

- [ ] **Step 3 [OWNER]: Rewire the phone + decommission**

Owner edits the Shortcut per the new doc section, records a REAL test session → email in ~2 min. Then:
```bash
launchctl unload ~/Library/LaunchAgents/com.guhan.hoops.plist   # plist kept for rollback
```
Owner deletes the three stale "Audio Recording *.m4a" strays from the iCloud inbox in Files.

- [ ] **Step 4: Commit**

```bash
git add docs/ CLAUDE.md README.md
git commit -m "docs: cloud pipeline as primary path; local mode as fallback; Shortcut rewire

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Golden-data acceptance gate

**Files:**
- Create: `scripts/cloud_acceptance.py` (committed — repeatable for future migrations)

**Interfaces:** Consumes the deployed endpoint (URL + key via env `HOOPS_ENDPOINT`, `HOOPS_UPLOAD_KEY`), `ObjectStore.from_env` (R2 env vars), `fixtures/manifest.csv` baselines.

- [ ] **Step 1: Write `scripts/cloud_acceptance.py`**

A self-contained script (stdlib + boto3 via cloud.store + urllib/requests-free using `urllib.request`):

```python
"""Golden-data acceptance gate for the cloud pipeline.

POSTs real fixture audio + one archived real session through the DEPLOYED
endpoint under fresh sids, waits for processing, pulls results from the
bucket, and compares canonical call sequences against the local baselines
(manifest machine columns / archived shots.csv). Exit 0 = gate passed.

Usage: set HOOPS_ENDPOINT, HOOPS_UPLOAD_KEY, R2_* env vars, then
  uv run python scripts/cloud_acceptance.py [--keep]
"""
import argparse, csv, io, json, os, sys, time, urllib.request, uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud.store import ObjectStore

CASES = [  # (audio path, baseline source)
    ("fixtures/F01_NormalSwishBrick.m4a", ("manifest", "F01_NormalSwishBrick.m4a")),
    ("fixtures/F02_SwishBrickChatty.m4a", ("manifest", "F02_SwishBrickChatty.m4a")),
    ("fixtures/F04_SwishBrickQuiet.m4a",  ("manifest", "F04_SwishBrickQuiet.m4a")),
    ("fixtures/07262026_MorningHoops.m4a", ("manifest", "07262026_MorningHoops.m4a")),
    ("sessions/2026/07/hoops__20260730-125100/audio.m4a",
     ("shots_csv", "sessions/2026/07/hoops__20260730-125100/shots.csv")),
]

def baseline_calls(kind, ref):
    if kind == "manifest":
        for row in csv.DictReader(open("fixtures/manifest.csv")):
            if row["filename"] == ref:
                return row["got_calls"].split()
        raise SystemExit(f"no manifest baseline for {ref}")
    rows = list(csv.DictReader(open(ref)))
    return [r["result"] for r in rows if r["voided"] not in ("True", "TRUE", "true")]

def post(endpoint, key, name, data):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{name}\"\r\nContent-Type: audio/mp4\r\n\r\n").encode() \
           + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{endpoint}/upload", data=body, method="POST",
        headers={"X-Hoops-Key": key,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def cloud_calls(store, sid):
    key = f"sessions/{sid[:4]}/{sid[4:6]}/hoops__{sid}/shots.csv"
    for _ in range(60):                      # up to 5 min per case
        if store.exists(key):
            rows = list(csv.DictReader(io.StringIO(store.get_bytes(key).decode())))
            return [r["result"] for r in rows if r["voided"] not in ("True", "TRUE", "true")]
        time.sleep(5)
    raise SystemExit(f"timed out waiting for {key}")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    endpoint, key = os.environ["HOOPS_ENDPOINT"], os.environ["HOOPS_UPLOAD_KEY"]
    store = ObjectStore.from_env()
    base_ts = datetime(2099, 1, 1)
    failures, test_sids = [], []
    for i, (audio, (kind, ref)) in enumerate(CASES, start=1):
        sid = (base_ts + timedelta(minutes=i)).strftime("%Y%m%d-%H%M%S")
        name = f"hoops__{sid}.m4a"
        ack = post(endpoint, key, name, Path(audio).read_bytes())
        print(f"{audio}: posted as {name} -> {ack}")
        got = cloud_calls(store, sid); test_sids.append(sid)
        want = baseline_calls(kind, ref)
        verdict = "MATCH" if got == want else "MISMATCH"
        print(f"  cloud={' '.join(got)}\n  base ={' '.join(want)}\n  {verdict}")
        if got != want:
            failures.append((audio, want, got))
    if not args.keep:
        for sid in test_sids:
            for k in store.list_keys(f"sessions/{sid[:4]}/{sid[4:6]}/hoops__{sid}/"):
                store.delete(k)
        print("test sessions cleaned from bucket")
    if failures:
        print(f"\nGATE FAILED: {len(failures)} mismatch(es)"); return 1
    print("\nGATE PASSED: cloud pipeline reproduces local baselines"); return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the gate (real APIs, ~10¢ whisper)**

`HOOPS_ENDPOINT=<url> HOOPS_UPLOAD_KEY=<key> uv run python scripts/cloud_acceptance.py` (R2 vars via `.env.r2`).
Expected: F01/F04/R01 and the 20-shot session MATCH; F02 (chatty trap) matches its baseline `miss miss` heard-set exactly (zero phantom calls beyond baseline). Additionally eyeball the five emails that arrive (the gate's side effect): the 20260730 re-run's email must show 20 shots, 10/10, flags I1+I6.
**Mismatch policy (spec):** investigate every mismatch; re-run the same audio through the LOCAL pipeline (`uv run hoops process <file> --no-email` on a copy) — if the local re-run reproduces the same divergence, it's whisper variance: document it in the ledger and amend the manifest notes; if not, it's a cloud-path bug: fix loop.

- [ ] **Step 3: Commit + record**

```bash
git add scripts/cloud_acceptance.py
git commit -m "test(cloud): golden-data acceptance gate against the deployed endpoint

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
Record the gate output verbatim in the SDD ledger.

---

### Task 7: Final whole-branch review + finish

- Per subagent-driven-development: review package over `d1ad3f4..HEAD`, most capable model, pointed at ledger minors + the acceptance-gate transcript; one fix wave max; then superpowers:finishing-a-development-branch (base `main`).
- Post-merge (owner rhythm): next real morning session arrives via the cloud; week-1 cost check on the Modal dashboard (≈$0 of $30) and R2 usage (KB-scale).

---

## Self-review notes (already applied)

- Spec coverage: architecture → Tasks 1-4; error handling contract → Task 2 tests + Task 4 alerting; golden gate → Task 6 (with the mismatch policy verbatim); docs/decommission/rollback → Task 5; R2-card + body-ceiling open items → Task 4 Steps 2-3; skills inventory lives in the spec.
- The `modal_app.py` code block deliberately includes a scaffolding-cleanup note (transcriber model from template, not hard-coded) — the implementer must apply it; the reviewer should check `"whisper-1"` appears nowhere in `cloud/`.
- `session_key_for` duplicates the `sid[:4]/sid[4:6]` layout from `session.session_dir_for` — acceptable coupling (bucket keys vs filesystem paths), pinned by `test_session_key_for`.
- Processor tests import `FakeClient` from `tests/test_cloud_store.py` — same pattern the repo already uses for `conftest` helpers.
- FakeClient lives in a test file imported cross-file (`from test_cloud_store import FakeClient`) — requires tests to be a package or path-inserted; the `sys.path.insert` lines handle it, matching the repo's existing `from conftest import make_env` style.
