import statistics
from .parse import Call, ParseResult
from .transcribe import Word

def build_shot_rows(calls: list[Call], session_id: str, session_date_local: str) -> list[dict]:
    rows, prev_t, streak = [], None, 0
    for i, c in enumerate(calls, start=1):
        gap = None
        if not c.voided:
            if prev_t is not None:
                gap = round(c.t_s - prev_t, 3)
            prev_t = c.t_s
            streak = streak + 1 if c.result == "make" else 0
        rows.append({
            "session_id": session_id, "session_date_local": session_date_local,
            "shot_num": i, "result": c.result, "t_call_s": c.t_s, "gap_s": gap,
            "streak_after": streak, "voided": c.voided, "isolation_s": c.isolation_s,
            "confidence": c.confidence, "raw_token": c.raw_token,
        })
    return rows

def _longest_streak(results: list[str], target: str) -> int:
    best = cur = 0
    for r in results:
        cur = cur + 1 if r == target else 0
        best = max(best, cur)
    return best

def build_chase(rows: list[dict]) -> dict:
    """Run structure of the session: consecutive same-result runs over live shots,
    how many two-in-a-row make runs got broken ('almosts'), and whether the
    session closed on three straight makes."""
    live = [r for r in rows if not r["voided"]]
    runs: list[dict] = []
    for r in live:
        if runs and runs[-1]["result"] == r["result"]:
            runs[-1]["end_shot"] = r["shot_num"]
            runs[-1]["end_t"] = r["t_call_s"]
            runs[-1]["length"] += 1
        else:
            runs.append({"result": r["result"], "start_shot": r["shot_num"],
                         "end_shot": r["shot_num"], "start_t": r["t_call_s"],
                         "end_t": r["t_call_s"], "length": 1})
    closed_out = bool(runs) and runs[-1]["result"] == "make" and runs[-1]["length"] >= 3
    almosts = sum(1 for i, run in enumerate(runs)
                  if run["result"] == "make" and run["length"] == 2
                  and i < len(runs) - 1)
    return {"runs": runs, "almosts": almosts, "closed_out": closed_out}

def build_session_stats(rows, parse: ParseResult, words: list[Word], *,
                        session_id, session_date_local, start_time_local,
                        session_len_s, transcriber, parser_version, profanity) -> dict:
    live = [r for r in rows if not r["voided"]]
    results = [r["result"] for r in live]
    makes, misses = results.count("make"), results.count("miss")
    gaps = [r["gap_s"] for r in live if r["gap_s"] is not None]
    first_make = next((r["t_call_s"] for r in live if r["result"] == "make"), None)
    pset = set(profanity)
    chase = build_chase(rows)
    return {
        "session_id": session_id, "session_date_local": session_date_local,
        "start_time_local": start_time_local,
        "shots_to_three": len(live),
        "makes": makes, "misses": misses,
        "fg_pct": (makes / len(live)) if live else None,
        "longest_make_streak": _longest_streak(results, "make"),
        "longest_miss_streak": _longest_streak(results, "miss"),
        "time_to_first_make_s": first_make,
        "median_gap_s": statistics.median(gaps) if gaps else None,
        "fastest_gap_s": min(gaps) if gaps else None,
        "slowest_gap_s": max(gaps) if gaps else None,
        "session_len_s": session_len_s,
        "notes": parse.note or "",
        "quote_of_day": "",
        "profanity_count": sum(1 for w in words if w.text in pset),
        "words_per_miss": (len(words) / misses) if misses else None,
        "invariants_passed": True,
        "ambiguous_calls": len(parse.ambiguous),
        "transcriber": transcriber, "parser_version": parser_version,
        "runs": chase["runs"],
        "almost_closeouts": chase["almosts"],
        "closed_out": chase["closed_out"],
    }
