"""SQLite trace persistence.

Stores traces, messages, tool calls, evidence summaries, verifications, and
errors for local inspection. Raw secrets are never stored; redaction is applied
upstream, and only evidence summaries (not full raw payloads) are persisted by
default.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT,
    timestamp TEXT NOT NULL,
    user_question TEXT,
    intent TEXT,
    final_answer TEXT,
    needs_clarification INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    service TEXT,
    action TEXT,
    target TEXT,
    status TEXT,
    duration_ms INTEGER,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    evidence_id TEXT,
    service TEXT,
    entity TEXT,
    action TEXT,
    records_returned INTEGER,
    query TEXT,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    supported INTEGER,
    unsupported_claims TEXT,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    code TEXT,
    message TEXT,
    timestamp TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TraceStore:
    """Thread-safe SQLite trace store."""

    def __init__(self, db_path: str = "./procurement_traces.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + explicit lock for FastAPI thread-pool safety.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- writes ---
    def ensure_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions(session_id, created_at) VALUES (?, ?)",
                (session_id, _now()),
            )
            self._conn.commit()

    def record_message(
        self,
        trace_id: str,
        session_id: str | None,
        user_question: str,
        intent: str | None,
        final_answer: str,
        needs_clarification: bool,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO messages
                   (trace_id, session_id, timestamp, user_question, intent,
                    final_answer, needs_clarification)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace_id,
                    session_id,
                    _now(),
                    user_question,
                    intent,
                    final_answer,
                    1 if needs_clarification else 0,
                ),
            )
            self._conn.commit()

    def record_tool_call(
        self,
        trace_id: str,
        service: str | None,
        action: str,
        target: str | None,
        status: str,
        duration_ms: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO tool_calls
                   (trace_id, service, action, target, status, duration_ms, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trace_id, service, action, target, status, duration_ms, _now()),
            )
            self._conn.commit()

    def record_evidence(
        self,
        trace_id: str,
        evidence_id: str,
        service: str,
        entity: str,
        action: str,
        records_returned: int,
        query: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO evidence
                   (trace_id, evidence_id, service, entity, action,
                    records_returned, query, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace_id,
                    evidence_id,
                    service,
                    entity,
                    action,
                    records_returned,
                    json.dumps(query),
                    _now(),
                ),
            )
            self._conn.commit()

    def record_verification(
        self, trace_id: str, supported: bool, unsupported_claims: list[str]
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO verifications
                   (trace_id, supported, unsupported_claims, timestamp)
                   VALUES (?, ?, ?, ?)""",
                (trace_id, 1 if supported else 0, json.dumps(unsupported_claims), _now()),
            )
            self._conn.commit()

    def record_error(self, trace_id: str, code: str, message: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO errors (trace_id, code, message, timestamp) VALUES (?, ?, ?, ?)",
                (trace_id, code, message, _now()),
            )
            self._conn.commit()

    # --- reads ---
    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            msg = self._conn.execute(
                "SELECT * FROM messages WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if msg is None:
                return None
            tool_calls = self._conn.execute(
                "SELECT * FROM tool_calls WHERE trace_id = ? ORDER BY id", (trace_id,)
            ).fetchall()
            evidence = self._conn.execute(
                "SELECT * FROM evidence WHERE trace_id = ? ORDER BY id", (trace_id,)
            ).fetchall()
            verifications = self._conn.execute(
                "SELECT * FROM verifications WHERE trace_id = ? ORDER BY id", (trace_id,)
            ).fetchall()
            errors = self._conn.execute(
                "SELECT * FROM errors WHERE trace_id = ? ORDER BY id", (trace_id,)
            ).fetchall()

        return {
            "message": dict(msg),
            "tool_calls": [dict(r) for r in tool_calls],
            "evidence": [dict(r) for r in evidence],
            "verifications": [dict(r) for r in verifications],
            "errors": [dict(r) for r in errors],
        }
