"""Committed attempt records survive failures; caller holds the process lock."""
from datetime import datetime, timezone
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
import sqlite3


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def signature(findings):
    def canonical(value):
        if isinstance(value, Decimal):
            return str(value.normalize())
        return str(value)
    payload = json.dumps([asdict(f) for f in findings if f.anomaly], default=canonical, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest(), payload


class AlertHistory:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('''CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY, reporting_date TEXT NOT NULL, signature TEXT NOT NULL,
            findings TEXT NOT NULL, detected_at TEXT NOT NULL, status TEXT NOT NULL,
            attempted_at TEXT, submission_result TEXT, error TEXT)''')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS successful_signature ON alerts(signature) WHERE status='submitted'")
        self.db.commit()

    def submitted(self, key):
        return self.db.execute("SELECT 1 FROM alerts WHERE signature=? AND status='submitted'", (key,)).fetchone() is not None

    def record(self, day, key, findings, status, attempted=False):
        with self.db:
            cursor = self.db.execute('''INSERT INTO alerts
                (reporting_date, signature, findings, detected_at, status, attempted_at)
                VALUES (?, ?, ?, ?, ?, ?)''', (str(day), key, findings, utc_now(), status, utc_now() if attempted else None))
        return cursor.lastrowid

    def finish(self, attempt, status, result, error=None):
        with self.db:
            self.db.execute('UPDATE alerts SET status=?, submission_result=?, error=? WHERE id=?',
                            (status, result, error, attempt))

    def close(self):
        self.db.close()
