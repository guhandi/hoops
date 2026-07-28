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
        cols = list(rows[0].keys())
        con.execute(f"CREATE TABLE {table} ({', '.join(c for c in cols)})")
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
                        [[json.dumps(r[c]) if isinstance(r.get(c), (dict, list))
                          else r.get(c) for c in cols] for r in rows])
    create("sessions", sess_rows)
    create("shots", shot_rows)
    con.commit()
    print(f"{db}: {len(sess_rows)} sessions, {len(shot_rows)} shots")

if __name__ == "__main__":
    main()
