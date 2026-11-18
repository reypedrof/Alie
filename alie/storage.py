import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "coupons.sqlite3")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
            source_url TEXT NOT NULL, status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sightings (
            run_id INTEGER NOT NULL REFERENCES runs(id),
            coupon_key TEXT NOT NULL, payload TEXT NOT NULL, seen_at TEXT NOT NULL,
            PRIMARY KEY(run_id, coupon_key));
        """)

    def start(self, url):
        with self.db:
            return self.db.execute(
                "INSERT INTO runs(started_at,source_url,status) VALUES(?,?,'running')",
                (now(), url)).lastrowid

    def save(self, run_id, coupon):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO sightings VALUES(?,?,?,?)",
                            (run_id, coupon.key, json.dumps(coupon.to_dict(), ensure_ascii=False), now()))

    def finish(self, run_id, status):
        with self.db:
            self.db.execute("UPDATE runs SET ended_at=?,status=? WHERE id=?", (now(), status, run_id))

    def results(self, run_id=None, min_percent=80, min_discount=0):
        if run_id is None:
            run_id = self.db.execute("SELECT MAX(id) FROM runs").fetchone()[0]
        rows = [json.loads(r[0]) for r in self.db.execute(
            "SELECT payload FROM sightings WHERE run_id=?", (run_id,))]
        rows = [r for r in rows if r["discount_cents"] * 100 >= min_percent * r["minimum_cents"]
                and r["discount_cents"] >= min_discount]
        # Cupons fortes primeiro; em empate priorizar maior desconto nominal.
        rows.sort(key=lambda r: (r["discount_cents"] / r["minimum_cents"], r["discount_cents"]), reverse=True)
        return run_id, rows

    def metadata(self, run_id):
        row = self.db.execute("SELECT started_at,ended_at,source_url,status FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(zip(("started_at", "ended_at", "source_url", "status"), row)) if row else {}
