"""SQLite-backed job store for the human-in-the-loop review workflow."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("processing", "needs_review", "approved", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    pdf BLOB NOT NULL,
    packages_json TEXT NOT NULL DEFAULT '[]',
    meta_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, data_dir: str | None = None):
        data_dir = data_dir or os.environ.get("DATA_DIR", "./data")
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.path = os.path.join(data_dir, "jobs.db")
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, filename: str, pdf: bytes) -> str:
        job_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO jobs (id, filename, status, pdf, created_at, updated_at) VALUES (?, ?, 'processing', ?, ?, ?)",
                (job_id, filename, pdf, now, now),
            )
        return job_id

    def set_result(self, job_id: str, packages: list[dict], meta: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='needs_review', packages_json=?, meta_json=?, updated_at=? WHERE id=?",
                (json.dumps(packages), json.dumps(meta), _now(), job_id),
            )

    def set_failed(self, job_id: str, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                (error, _now(), job_id),
            )

    def update_packages(self, job_id: str, packages: list[dict]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET packages_json=?, updated_at=? WHERE id=?",
                (json.dumps(packages), _now(), job_id),
            )

    def approve(self, job_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='approved', updated_at=? WHERE id=?",
                (_now(), job_id),
            )

    def get(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, filename, status, packages_json, meta_json, error, created_at, updated_at FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "filename": row["filename"],
            "status": row["status"],
            "packages": json.loads(row["packages_json"]),
            "meta": json.loads(row["meta_json"]),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_pdf(self, job_id: str) -> bytes | None:
        with self._conn() as conn:
            row = conn.execute("SELECT pdf FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["pdf"] if row else None

    def list(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, filename, status, packages_json, error, created_at, updated_at "
                "FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "filename": r["filename"],
                "status": r["status"],
                "package_count": len(json.loads(r["packages_json"])),
                "error": r["error"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
