"""GuData push: session stats + per-shot rows -> POST /api/ingest/hoops_shooting.

Additive and non-fatal by design: the report/email path never depends on this
module. Server-side idempotency via external_id makes retries/backfills safe.
Pure stdlib (hmac/base64/urllib) — no new dependencies.
"""
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
