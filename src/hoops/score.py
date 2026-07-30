import csv, difflib, json, os, tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from .config import Config
from .fixtures import read_manifest, transcript_cache_path
from .invariants import check_invariants
from .parse import parse_words
from .stats import build_shot_rows
from .transcribe import words_from_envelope

GATES = {"recall": 0.99, "precision": 0.99, "classification": 0.98,
         "exact_fraction": 0.90, "gap_mae": 0.5}

MACHINE_COLS = ["heard_calls", "got_calls", "match", "scored_at"]

def update_manifest(manifest_path, scores, scored_at: str) -> None:
    """Write machine columns back into the manifest. Hand columns are never
    touched; only rows present in `scores` are updated; atomic replace."""
    by_name = {s.name: s for s in scores}
    with manifest_path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    names = [r["filename"] for r in rows]
    dups = sorted({n for n in names if names.count(n) > 1 and n})
    if dups:
        raise ValueError(f"manifest has duplicate filename rows: {', '.join(dups)} — "
                         "fix fixtures/manifest.csv before scoring")
    for col in MACHINE_COLS:
        if col not in fieldnames:
            fieldnames.append(col)
    for r in rows:
        for col in MACHINE_COLS:
            r.setdefault(col, "")
        s = by_name.get(r["filename"])
        if s is None:
            continue
        r["heard_calls"] = " ".join(s.heard)
        r["got_calls"] = " ".join(s.got)
        r["match"] = "TRUE" if s.got == s.expected else "FALSE"
        r["scored_at"] = scored_at
    fd, tmp = tempfile.mkstemp(dir=manifest_path.parent, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, manifest_path)
    except BaseException:
        os.unlink(tmp)
        raise

@dataclass
class FixtureScore:
    name: str
    expected: list
    got: list
    heard: list
    matched: int
    inserted: int
    deleted: int
    misclassified: int
    exact: bool
    gap_mae: float | None
    traps: bool
    invariants_ok_expected: bool
    invariants_ok_got: bool

def score_fixture(row: dict, cfg: Config) -> FixtureScore | None:
    if not row.get("expected_calls"):
        return None
    cache = transcript_cache_path(cfg.repo_root, row["filename"])
    if not cache.exists():
        return None
    env = json.loads(cache.read_text())
    vocab = cfg.vocab(row.get("vocabulary") or None)
    parsed = parse_words(words_from_envelope(env), vocab,
                         cfg.isolation_low, cfg.isolation_high)
    live = [c for c in parsed.calls if not c.voided]
    got = [c.result for c in live]
    heard = [c.raw_token for c in live]
    expected = row["expected_calls"].split()
    sm = difflib.SequenceMatcher(a=expected, b=got, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    mis = sum(min(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes()
              if tag == "replace")
    rows = build_shot_rows(parsed.calls, "score", "1970-01-01")
    inv_got = not check_invariants(rows, min_gap_s=cfg.min_gap_s,
                                   max_gap_s=cfg.max_gap_s, vocab=vocab)
    gap_mae = None
    if row.get("expected_gaps"):
        exp_gaps = [float(x) for x in row["expected_gaps"].split()]
        got_gaps = [r["gap_s"] for r in rows if not r["voided"] and r["gap_s"] is not None]
        if len(exp_gaps) == len(got_gaps):
            gap_mae = sum(abs(a - b) for a, b in zip(exp_gaps, got_gaps)) / len(exp_gaps)
    traps = bool(row.get("traps_planted", "").strip()) and row["traps_planted"].strip() != "0"
    return FixtureScore(name=row["filename"], expected=expected, got=got, heard=heard,
                        matched=matched, inserted=len(got) - matched,
                        deleted=len(expected) - matched, misclassified=mis,
                        exact=expected == got, gap_mae=gap_mae, traps=traps,
                        invariants_ok_expected=row.get("expect_invariants_pass", "TRUE").strip().upper() in ("TRUE", "YES"),
                        invariants_ok_got=inv_got)

def aggregate(scores: list[FixtureScore]) -> dict:
    te = sum(len(s.expected) for s in scores) or 1
    tg = sum(len(s.got) for s in scores) or 1
    tm = sum(s.matched for s in scores)
    mis = sum(s.misclassified for s in scores)
    maes = [s.gap_mae for s in scores if s.gap_mae is not None]
    return {
        "recall": tm / te,
        "precision": tm / tg,
        "classification": tm / (tm + mis) if (tm + mis) else 1.0,
        "exact_fraction": sum(s.exact for s in scores) / (len(scores) or 1),
        "gap_mae": (sum(maes) / len(maes)) if maes else None,
        "phantom_on_traps": sum(s.inserted for s in scores if s.traps),
        "invariant_mismatches": sum(1 for s in scores
                                    if s.invariants_ok_got != s.invariants_ok_expected),
    }

def score_and_print(cfg: Config) -> int:
    rows = read_manifest(cfg.repo_root / "fixtures" / "manifest.csv")
    gating, info = [], []
    for r in rows:
        s = score_fixture(r, cfg)
        if s is None:
            continue
        (gating if r.get("use_for", "").strip().upper() == "GATE" else info).append(s)
    scored = gating + info
    if scored:
        update_manifest(cfg.repo_root / "fixtures" / "manifest.csv", scored,
                        scored_at=date.today().isoformat())
    agg = aggregate(gating) if gating else None
    print(f"{'fixture':<28}{'expected':<10}{'got':<10}exact")
    for s in gating + info:
        tag = "" if s in gating else "  (non-gating)"
        print(f"{s.name:<28}{len(s.expected):<10}{len(s.got):<10}{s.exact}{tag}")
    if not gating:
        print("\nNo gating fixtures with cached transcripts yet — gates not evaluated.")
        return 0
    ok = True
    print("\nGate table:")
    for k, gate in GATES.items():
        val = agg[k]
        if k == "gap_mae":
            passed = val is None or val <= gate
            shown = "n/a" if val is None else f"{val:.2f}s"
        else:
            passed = val >= gate
            shown = f"{val:.3f}"
        ok &= passed
        print(f"  {k:<16}{shown:>8}   gate {gate}   {'PASS' if passed else 'FAIL'}")
    phantom_ok = agg["phantom_on_traps"] == 0
    ok &= phantom_ok
    print(f"  {'phantom_on_traps':<16}{agg['phantom_on_traps']:>8}   gate 0   "
          f"{'PASS' if phantom_ok else 'FAIL (hard build failure)'}")
    inv_ok = agg["invariant_mismatches"] == 0
    ok &= inv_ok
    print(f"  {'invariant_mismatches':<16}{agg['invariant_mismatches']:>8}   gate 0   "
          f"{'PASS' if inv_ok else 'FAIL (hard build failure)'}")
    return 0 if ok else 1
