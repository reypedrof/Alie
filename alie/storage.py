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
            source_url TEXT NOT NULL, status TEXT NOT NULL, rounds_completed INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS sightings (
            run_id INTEGER NOT NULL REFERENCES runs(id),
            coupon_key TEXT NOT NULL, payload TEXT NOT NULL, seen_at TEXT NOT NULL, first_seen_at TEXT,
            PRIMARY KEY(run_id, coupon_key));
        """)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if "rounds_completed" not in {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}:
                self.db.execute("ALTER TABLE runs ADD COLUMN rounds_completed INTEGER NOT NULL DEFAULT 0")
            if "first_seen_at" not in {row[1] for row in self.db.execute("PRAGMA table_info(sightings)")}:
                self.db.execute("ALTER TABLE sightings ADD COLUMN first_seen_at TEXT")
                self.db.execute("UPDATE sightings SET first_seen_at=seen_at")
            self.db.execute("CREATE INDEX IF NOT EXISTS sightings_coupon_first_seen ON sightings(coupon_key, first_seen_at)")

    def start(self, url):
        with self.db:
            return self.db.execute(
                "INSERT INTO runs(started_at,source_url,status) VALUES(?,?,'running')",
                (now(), url)).lastrowid

    def save(self, run_id, coupon):
        self.save_many(run_id, [coupon])

    def save_many(self, run_id, coupons):
        seen_at = now()
        with self.db:
            self.db.executemany("""
                INSERT INTO sightings(run_id,coupon_key,payload,seen_at,first_seen_at) VALUES(?,?,?,?,?)
                ON CONFLICT(run_id,coupon_key) DO UPDATE SET payload=excluded.payload, seen_at=excluded.seen_at
            """, ((run_id, coupon.key, json.dumps(coupon.to_dict(), ensure_ascii=False), seen_at, seen_at)
                  for coupon in coupons))

    def complete_round(self, run_id, number):
        with self.db:
            self.db.execute("UPDATE runs SET rounds_completed=? WHERE id=?", (number, run_id))

    def finish(self, run_id, status):
        with self.db:
            self.db.execute("UPDATE runs SET ended_at=?,status=? WHERE id=?", (now(), status, run_id))

    def results(self, run_id=None, min_percent=80, min_discount=0):
        if run_id is None:
            run_id = self.db.execute("SELECT MAX(id) FROM runs").fetchone()[0]
        rows = [{**json.loads(payload), "first_seen_at": first_seen, "last_seen_at": last_seen}
                for payload, first_seen, last_seen in self.db.execute("""
                    SELECT s.payload, (SELECT MIN(h.first_seen_at) FROM sightings h WHERE h.coupon_key=s.coupon_key),
                           s.seen_at
                    FROM sightings s WHERE s.run_id=?
                """, (run_id,))]
        rows = [r for r in rows if r["discount_cents"] * 100 >= min_percent * r["minimum_cents"]
                and r["discount_cents"] >= min_discount]
        # Cupons fortes primeiro; em empate priorizar maior desconto nominal.
        rows.sort(key=lambda r: (r["discount_cents"] / r["minimum_cents"], r["discount_cents"]), reverse=True)
        return run_id, rows

    def metadata(self, run_id):
        row = self.db.execute("SELECT started_at,ended_at,source_url,status,rounds_completed FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(zip(("started_at", "ended_at", "source_url", "status", "rounds_completed"), row)) if row else {}
