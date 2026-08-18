"""GuData push: session stats + per-shot rows -> POST /api/ingest/hoops_shooting.

Additive and non-fatal by design: the report/email path never depends on this
module. Server-side idempotency via external_id makes retries/backfills safe.
Pure stdlib (hmac/base64/urllib) — no new dependencies.
"""
import base64, hashlib, hmac, json, os, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

INSTRUMENT_ID = "hoops_shooting"

class GuDataError(RuntimeError):
    pass

def build_payload(stats: dict, rows: list[dict], tz_name: str,
                  external_id: str) -> dict:
    live = [r for r in rows if not r["voided"]]
    if not live:
        raise GuDataError("no live shots to push")
    start = datetime.strptime(stats["session_id"], "%Y%m%d-%H%M%S").replace(
        tzinfo=ZoneInfo(tz_name))
    values = {
        "activity.hoops.shots_to_three": int(stats["shots_to_three"]),
        "activity.hoops.fg_pct": round(float(stats["fg_pct"]) * 100, 1),
        "activity.hoops.longest_streak": int(stats["longest_make_streak"]),
        "activity.hoops.shot_count": len(live),
    }
    if stats.get("notes"):
        values["activity.hoops.session_notes"] = stats["notes"]
    return {
        "session": {"observed_at": start.isoformat(), "timezone": tz_name,
                    "values": values},
        "rows": [{"field": "activity.hoops.shot_result",
                  "value": r["result"] == "make",
                  "observed_at": (start + timedelta(seconds=float(r["t_call_s"]))).isoformat()}
                 for r in live],
        "external_id": external_id,
    }

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def mint_jwt(secret: str, subject: str, now: int | None = None) -> str:
    """HS256 JWT the way DayReel's mintJwt does it — 10-minute expiry."""
    iat = int(time.time()) if now is None else now
    seg = lambda obj: _b64url(json.dumps(obj, separators=(",", ":")).encode())
    signing = f'{seg({"alg": "HS256", "typ": "JWT"})}.{seg({"sub": subject, "aud": "authenticated", "iat": iat, "exp": iat + 600})}'
    sig = hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{_b64url(sig)}"

def post_json(url: str, body: dict, token: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def push_payload(payload: dict) -> dict:
    env = {k: os.environ.get(k, "").strip()
           for k in ("GUDATA_API_URL", "GUDATA_JWT_SECRET", "GUDATA_SUBJECT_ID")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise GuDataError(f"missing env: {', '.join(missing)}")
    token = mint_jwt(env["GUDATA_JWT_SECRET"], env["GUDATA_SUBJECT_ID"])
    url = f"{env['GUDATA_API_URL'].rstrip('/')}/api/ingest/{INSTRUMENT_ID}"
    return post_json(url, payload, token)
