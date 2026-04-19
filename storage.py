"""
SQLite-backed persistence for Fence sessions and audit events.

This keeps the project self-contained while making it behave more like a real
service: requests, decisions, and session state survive process restarts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FenceAuditEvent:
    """A persisted audit event for a normalized tool call."""

    event_id: str
    session_id: str
    agent_id: str
    tool_name: str
    decision: str
    reason: str
    created_at: str
    metadata: Dict[str, Any]


class FenceStore:
    """Small SQLite store for sessions and audit history."""

    def __init__(self, db_path: str = "fence.db"):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    timeout_minutes INTEGER NOT NULL,
                    token_budget INTEGER NOT NULL,
                    cost_budget REAL NOT NULL,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    cost_used REAL NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.commit()

    def upsert_session(
        self,
        session_id: str,
        agent_id: str,
        created_at: datetime,
        expires_at: datetime,
        timeout_minutes: int,
        token_budget: int,
        cost_budget: float,
        tokens_used: int = 0,
        cost_used: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = json.dumps(metadata or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, agent_id, created_at, expires_at,
                    timeout_minutes, token_budget, cost_budget,
                    tokens_used, cost_used, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id=excluded.agent_id,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    timeout_minutes=excluded.timeout_minutes,
                    token_budget=excluded.token_budget,
                    cost_budget=excluded.cost_budget,
                    tokens_used=excluded.tokens_used,
                    cost_used=excluded.cost_used,
                    metadata=excluded.metadata
                """,
                (
                    session_id,
                    agent_id,
                    created_at.isoformat(),
                    expires_at.isoformat(),
                    timeout_minutes,
                    token_budget,
                    cost_budget,
                    tokens_used,
                    cost_used,
                    payload,
                ),
            )
            conn.commit()

    def update_usage(
        self,
        session_id: str,
        tokens_used: int,
        cost_used: float,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET tokens_used = ?,
                    cost_used = ?
                WHERE session_id = ?
                """,
                (tokens_used, cost_used, session_id),
            )
            conn.commit()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
            return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0

    def record_audit_event(
        self,
        event_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        decision: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id, session_id, agent_id, tool_name, decision,
                    reason, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    agent_id,
                    tool_name,
                    decision,
                    reason,
                    datetime.utcnow().isoformat() + "Z",
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()

    def list_audit_events(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_events"
        params: tuple[Any, ...] = ()
        if session_id:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
