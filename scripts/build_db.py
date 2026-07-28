"""Rebuild hoops.db from committed session text. Derived, disposable (PRD §7.4)."""
import argparse, csv, json, sqlite3
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default="sessions")
    ap.add_argument("--db", default="hoops.db")
    a = ap.parse_args()
    root, db = Path(a.sessions), Path(a.db)
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    shot_rows, sess_rows = [], []
    for sj in sorted(root.rglob("session.json")):
        sess_rows.append(json.loads(sj.read_text()))
        with (sj.parent / "shots.csv").open() as f:
            shot_rows.extend(list(csv.DictReader(f)))
    if not sess_rows:
        print("no sessions found"); return
    def create(table, rows):
        # Build column list as union of keys across all rows, preserving first-seen order
        cols = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    cols.append(key)
                    seen.add(key)
        # CREATE TABLE with quoted identifiers
        col_defs = ', '.join(f'"{c}"' for c in cols)
        con.execute(f"CREATE TABLE {table} ({col_defs})")
        # INSERT with r.get(c) to handle missing keys as NULL
        placeholders = ', '.join('?' * len(cols))
        values = []
        for row in rows:
            row_values = []
            for col in cols:
                val = row.get(col)
                if isinstance(val, (dict, list)):
                    row_values.append(json.dumps(val))
                else:
                    row_values.append(val)
            values.append(row_values)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", values)
    create("sessions", sess_rows)
    create("shots", shot_rows)
    con.commit()
    print(f"{db}: {len(sess_rows)} sessions, {len(shot_rows)} shots")

if __name__ == "__main__":
    main()
