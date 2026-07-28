from dataclasses import dataclass
from .config import Vocabulary
from .transcribe import normalize_token

@dataclass(frozen=True)
class Violation:
    id: str
    message: str

def check_invariants(rows: list[dict], *, min_gap_s: float, max_gap_s: float,
                     vocab: Vocabulary) -> list[Violation]:
    v: list[Violation] = []
    live = [r for r in rows if not r["voided"]]
    results = [r["result"] for r in live]

    if len(live) < 3:
        v.append(Violation("I2", f"only {len(live)} non-voided calls (< 3)"))
    if results[-3:] != ["make", "make", "make"]:
        v.append(Violation("I1", f"final three calls are {results[-3:]}, not all makes"))
    for r in live:
        if r["gap_s"] is not None and r["gap_s"] < min_gap_s:
            v.append(Violation("I3", f"shot {r['shot_num']}: gap {r['gap_s']}s < {min_gap_s}s"))
        if r["gap_s"] is not None and r["gap_s"] > max_gap_s:
            v.append(Violation("I4", f"shot {r['shot_num']}: gap {r['gap_s']}s > {max_gap_s}s"))
    known = set(vocab.surface_to_canonical)
    for r in rows:
        if normalize_token(r["raw_token"]) not in known:
            v.append(Violation("I5", f"shot {r['shot_num']}: raw_token {r['raw_token']!r} not in vocabulary"))
    streak = 0
    for i, res in enumerate(results):
        streak = streak + 1 if res == "make" else 0
        if streak == 3 and i != len(results) - 1:
            v.append(Violation("I6", f"three-make run ends at call {i + 1}, before the final call"))
            break
    return v
