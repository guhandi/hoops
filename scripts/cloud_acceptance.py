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
